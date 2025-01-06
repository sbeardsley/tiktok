from datetime import datetime
import time


def parse_date_1(date_str):
    """create_sorted_set.py version"""
    try:
        if "·" in date_str:
            date_str = date_str.split("·")[1].strip()
        return datetime.strptime(date_str, "%Y-%m-%d").timestamp()
    except:
        return time.time()


def parse_date_2(date_str):
    """metadata_service.py version"""
    try:
        date_part = date_str.split("·")[-1].strip()
        return time.mktime(time.strptime(date_part, "%Y-%m-%d"))
    except Exception as e:
        print(f"Error: {e}")
        return time.time()


# Test cases
test_dates = [
    "2024-01-05",
    "username·2024-01-05",
    "The Cheese Knees·2024-01-05",
    "2023-12-31",
    "invalid date",
    "novaalignedNova·2019-11-10",
    "mama_peyymama_peyy\xc2\xb72024-11-7",
]

print("Comparing parse functions:")
for date in test_dates:
    result1 = parse_date_1(date)
    result2 = parse_date_2(date)
    print(f"\nInput: {date}")
    print(f"parse_date_1: {result1} ({datetime.fromtimestamp(result1)})")
    print(f"parse_date_2: {result2} ({datetime.fromtimestamp(result2)})")
    if result1 != result2:
        print(f"*** DIFFERENCE: {result2 - result1} seconds")
