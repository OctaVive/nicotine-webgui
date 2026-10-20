import hashlib


def resource_id(user, path):
    return hashlib.sha1((user + "\0" + path).encode("utf-8")).hexdigest()[:20]


def transfer(item):
    fields = ("username", "virtual_path", "size", "status", "current_byte_offset", "speed",
              "time_left", "queue_position")
    result = {key: getattr(item, key, None) for key in fields}
    for key in ("size", "current_byte_offset", "speed", "time_left", "queue_position"):
        result[key] = result[key] or 0
    result["status"] = result["status"] or "Unknown"
    result["id"] = resource_id(item.username, item.virtual_path)
    return result
