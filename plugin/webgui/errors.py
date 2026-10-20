class APIError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def text(value, name, maximum=1024):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or "\x00" in value:
        raise APIError(400, "validation", f"{name} must be a non-empty string of at most {maximum} characters")
    return value


def integer(value, name, minimum=0, maximum=2147483647):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise APIError(400, "validation", f"{name} must be an integer between {minimum} and {maximum}")
    return value
