"""Reject non-SELECT SQL."""
from app.tools.query_data import QueryValidationError, validate_select_sql


def test_rejects_drop():
    try:
        validate_select_sql("DROP TABLE sample_sales", {"sample_sales"})
        assert False, "should have raised"
    except QueryValidationError:
        pass


def test_allows_select():
    sql = validate_select_sql(
        "SELECT region, SUM(revenue) AS total FROM sample_sales GROUP BY region",
        {"sample_sales"},
    )
    assert "SELECT" in sql.upper()


if __name__ == "__main__":
    test_rejects_drop()
    test_allows_select()
    print("validation ok")
