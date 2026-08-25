def checkout(items: list[int]) -> dict[str, int | str]:
    total = sum(items)
    average = total // len(items)
    return {"status": "ok", "total": total, "average": average}
