"""Convert persisted job data into the API's entry representation."""


def job_entries(data: dict, status: str) -> list[dict]:
    results = data.get("results") or []
    if results:
        return [{"entry_index": idx, "input": item.get("input"),
                 "status": item.get("status", status), "path": item.get("path"),
                 "deleted_path": item.get("deleted_path"), "error": item.get("error")}
                for idx, item in enumerate(results)]
    return [{"entry_index": idx, "input": item, "status": status,
             "path": None, "deleted_path": None,
             "error": data.get("error") if status == "error" else None}
            for idx, item in enumerate(data.get("entries", []))]
