from django.shortcuts import render


def error_403(request, exception=None):
    message = str(exception) if exception and str(exception) else "Доступ запрещён"
    return render(request, "core/error.html", {"code": 403, "title": message,
                                               "text": "У вашей роли нет прав на этот раздел или объект. "
                                                       "Если доступ нужен для работы, обратитесь к ГИПу или директору."},
                  status=403)


def error_404(request, exception=None):
    return render(request, "core/error.html", {"code": 404, "title": "Страница не найдена",
                                               "text": "Возможно, ссылка устарела или объект был перемещён в архив."},
                  status=404)


def error_500(request):
    return render(request, "core/error.html", {"code": 500, "title": "Внутренняя ошибка",
                                               "text": "Действие не выполнено. Повторите попытку позже; "
                                                       "если ошибка повторяется — сообщите администратору."},
                  status=500)
