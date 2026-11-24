from django.http import HttpResponseBadRequest


class InputValidationMiddleware:
    """Reject NUL characters before search parameters reach PostgreSQL."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        for parameters in (request.GET, request.POST):
            for key, values in parameters.lists():
                if "\x00" in key or any("\x00" in value for value in values):
                    return HttpResponseBadRequest(
                        "Dữ liệu gửi lên chứa ký tự không hợp lệ.",
                        content_type="text/plain; charset=utf-8",
                    )
        return self.get_response(request)
