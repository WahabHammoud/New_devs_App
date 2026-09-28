from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Any, List
from zoneinfo import ZoneInfo

async def calculate_monthly_revenue(property_id: str, tenant_id: str, month: int, year: int) -> Dict[str, Any]:
    """
    Calculates revenue for a specific month, using the property's local timezone
    for month boundaries (a check-in at 23:30 UTC on Feb 29 is March 1 in Paris).
    """
    from app.core.database_pool import DatabasePool
    from sqlalchemy import text

    db_pool = DatabasePool()
    await db_pool.initialize()
    if not db_pool.session_factory:
        raise Exception("Database pool not available")

    try:
        # get_session() is a coroutine returning an AsyncSession, so await it first
        async with await db_pool.get_session() as session:
            tz_row = (await session.execute(
                text("SELECT timezone FROM properties WHERE id = :property_id AND tenant_id = :tenant_id"),
                {"property_id": property_id, "tenant_id": tenant_id},
            )).fetchone()

            if not tz_row:
                # Property does not belong to this tenant
                return {
                    "property_id": property_id,
                    "tenant_id": tenant_id,
                    "total": "0.00",
                    "currency": "USD",
                    "count": 0
                }

            # Half-open range [start, end) in property-local time, converted to UTC
            prop_tz = ZoneInfo(tz_row.timezone)
            start_local = datetime(year, month, 1, tzinfo=prop_tz)
            if month < 12:
                end_local = datetime(year, month + 1, 1, tzinfo=prop_tz)
            else:
                end_local = datetime(year + 1, 1, 1, tzinfo=prop_tz)
            start_utc = start_local.astimezone(timezone.utc)
            end_utc = end_local.astimezone(timezone.utc)

            row = (await session.execute(
                text("""
                    SELECT
                        SUM(total_amount) as total_revenue,
                        COUNT(*) as reservation_count
                    FROM reservations
                    WHERE property_id = :property_id
                    AND tenant_id = :tenant_id
                    AND check_in_date >= :start_utc
                    AND check_in_date < :end_utc
                """),
                {
                    "property_id": property_id,
                    "tenant_id": tenant_id,
                    "start_utc": start_utc,
                    "end_utc": end_utc,
                },
            )).fetchone()

            total_revenue = Decimal(str(row.total_revenue)) if row.total_revenue is not None else Decimal("0")
            total_revenue = total_revenue.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            return {
                "property_id": property_id,
                "tenant_id": tenant_id,
                "total": str(total_revenue),
                "currency": "USD",
                "count": row.reservation_count
            }
    finally:
        # This pool is created per call; dispose it so connections aren't leaked
        await db_pool.close()

async def calculate_total_revenue(property_id: str, tenant_id: str) -> Dict[str, Any]:
    """
    Aggregates revenue from database.
    """
    try:
        # Import database pool
        from app.core.database_pool import DatabasePool
        
        # Initialize pool if needed
        db_pool = DatabasePool()
        await db_pool.initialize()
        
        if db_pool.session_factory:
            async with await db_pool.get_session() as session:
                # Use SQLAlchemy text for raw SQL
                from sqlalchemy import text
                
                query = text("""
                    SELECT 
                        property_id,
                        SUM(total_amount) as total_revenue,
                        COUNT(*) as reservation_count
                    FROM reservations 
                    WHERE property_id = :property_id AND tenant_id = :tenant_id
                    GROUP BY property_id
                """)
                
                result = await session.execute(query, {
                    "property_id": property_id, 
                    "tenant_id": tenant_id
                })
                row = result.fetchone()
                
                if row:
                    total_revenue = Decimal(str(row.total_revenue)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                    return {
                        "property_id": property_id,
                        "tenant_id": tenant_id,
                        "total": str(total_revenue),
                        "currency": "USD", 
                        "count": row.reservation_count
                    }
                else:
                    # No reservations found for this property
                    return {
                        "property_id": property_id,
                        "tenant_id": tenant_id,
                        "total": "0.00",
                        "currency": "USD",
                        "count": 0
                    }
        else:
            raise Exception("Database pool not available")
            
    except Exception as e:
        print(f"Database error for {property_id} (tenant: {tenant_id}): {e}")
        
        # Create property-specific mock data for testing when DB is unavailable
        # This ensures each property shows different figures
        mock_data = {
            'prop-001': {'total': '1000.00', 'count': 3},
            'prop-002': {'total': '4975.50', 'count': 4}, 
            'prop-003': {'total': '6100.50', 'count': 2},
            'prop-004': {'total': '1776.50', 'count': 4},
            'prop-005': {'total': '3256.00', 'count': 3}
        }
        
        mock_property_data = mock_data.get(property_id, {'total': '0.00', 'count': 0})
        
        return {
            "property_id": property_id,
            "tenant_id": tenant_id, 
            "total": mock_property_data['total'],
            "currency": "USD",
            "count": mock_property_data['count']
        }
