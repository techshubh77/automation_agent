class AppError(Exception):
    """
    Custom Error Class for Application Errors
    """

    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.status = "fail" if str(status_code).startswith("4") else "error"
        self.is_operational = True
