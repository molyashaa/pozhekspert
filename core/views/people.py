"""Справочник клиентов и учётные записи сотрудников (п. 3.1, 5.7, 5.9 ТЗ)."""
import secrets
import string

from django.contrib import messages
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from ..forms import ClientForm, EmployeeForm
from ..models import Client, Role, User
from ..permissions import can_manage_clients, can_manage_users, can_view_clients, can_view_employees, require
from ..services import BusinessError, audit, workload
from .common import business_action, paginate


def generate_password(length=10):
    alphabet = string.ascii_letters + string.digits
    while True:
        pwd = "".join(secrets.choice(alphabet) for _ in range(length - 2)) + secrets.choice("!#%+") + secrets.choice(string.digits)
        if any(c.isupper() for c in pwd) and any(c.islower() for c in pwd):
            return pwd


# ---------------------------------------------------------------------------
# Клиенты
# ---------------------------------------------------------------------------
def client_list(request):
    user = request.user
    require(can_view_clients(user), "Раздел «Клиенты» доступен директору и уполномоченным сотрудникам")
    qs = Client.objects.annotate(projects_count=Count("projects")).select_related("updated_by")
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "active")
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(contact_person__icontains=q) | Q(inn__icontains=q)
                       | Q(email__icontains=q))
    if status in ("active", "archived"):
        qs = qs.filter(status=status)
    return render(request, "core/clients.html", {
        "page": paginate(request, qs.order_by("name"), 15), "q": q, "status": status,
        "can_manage": can_manage_clients(user),
    })


def client_form(request, pk=None):
    user = request.user
    require(can_manage_clients(user), "Вести справочник клиентов может директор или сотрудник с делегированным правом")
    client = get_object_or_404(Client, pk=pk) if pk else None
    old = {f: getattr(client, f) for f in ("name", "contact_person", "phone", "email", "address", "inn")} if client else {}
    form = ClientForm(request.POST or None, instance=client)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        if not obj.pk:
            obj.created_by = user
        obj.updated_by = user
        obj.save()
        if client:
            for field, value in old.items():
                if value != getattr(obj, field):
                    audit(user, "client_changed", f"Клиент «{obj.name}»: изменено поле «{Client._meta.get_field(field).verbose_name}»",
                          obj, None, value, getattr(obj, field))
            messages.success(request, "Данные клиента сохранены.")
        else:
            audit(user, "client_created", f"Добавлен клиент «{obj.name}»", obj)
            messages.success(request, f"Клиент «{obj.name}» добавлен в справочник.")
        nxt = request.POST.get("next", "")
        if nxt.startswith("/") and not nxt.startswith("//"):
            return redirect(nxt)
        return redirect("clients")
    return render(request, "core/client_form.html", {"form": form, "client": client,
                                                     "next": request.GET.get("next", "")})


@require_POST
def client_archive(request, pk):
    user = request.user
    require(can_manage_clients(user))
    client = get_object_or_404(Client, pk=pk)
    if client.status == "active":
        client.status = "archived"
        msg = f"Клиент «{client.name}» переведён в архив. Связанные проекты и история сохранены."
    else:
        client.status = "active"
        msg = f"Клиент «{client.name}» снова активен."
    client.updated_by = user
    client.save()
    audit(user, "client_status", msg, client)
    messages.success(request, msg)
    return redirect("clients")


# ---------------------------------------------------------------------------
# Сотрудники и учётные записи
# ---------------------------------------------------------------------------
def employee_list(request):
    user = request.user
    require(can_view_employees(user), "Раздел «Сотрудники» доступен директору")
    qs = User.objects.select_related("role")
    q = request.GET.get("q", "").strip()
    role = request.GET.get("role", "")
    status = request.GET.get("status", "")
    if q:
        qs = qs.filter(Q(full_name__icontains=q) | Q(email__icontains=q))
    if role:
        qs = qs.filter(role__code=role)
    if status:
        qs = qs.filter(status=status)
    qs = qs.order_by("role_id", "full_name")
    selected = None
    if request.GET.get("id"):
        selected = User.objects.filter(pk=request.GET["id"]).select_related("role").first()
    elif qs.exists():
        selected = qs.first()
    temp = request.session.pop("temp_password", None)
    return render(request, "core/employees.html", {
        "employees": qs, "q": q, "role": role, "status": status, "roles": Role.objects.all(),
        "statuses": User.STATUS_CHOICES, "selected": selected,
        "load": workload(selected) if selected and selected.is_executor_role else None,
        "can_manage": can_manage_users(user), "temp": temp,
    })


def employee_form(request, pk=None):
    user = request.user
    require(can_manage_users(user), "Учётные записи создаёт директор или уполномоченный им сотрудник")
    employee = get_object_or_404(User, pk=pk) if pk else None
    old_role = employee.role.name if employee else ""
    form = EmployeeForm(request.POST or None, instance=employee)
    if not user.is_director:
        # делегированное право не позволяет раздавать административные полномочия
        form.fields.pop("can_manage_users")
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        if employee is None:
            password = generate_password()
            obj.set_password(password)
            obj.must_change_password = True
            obj.save()
            audit(user, "user_created", f"Создана учётная запись {obj.short_name} ({obj.email}), роль «{obj.role.name}»", obj)
            request.session["temp_password"] = {"email": obj.email, "password": password, "name": obj.short_name}
            messages.success(request, "Учётная запись создана. Передайте сотруднику временный пароль — "
                                      "он показывается один раз.")
        else:
            obj.save()
            if old_role != obj.role.name:
                audit(user, "role_changed", f"Изменена роль сотрудника {obj.short_name}", obj, None, old_role, obj.role.name)
            audit(user, "user_changed", f"Изменены данные учётной записи {obj.short_name}", obj)
            messages.success(request, "Данные сотрудника сохранены. Новая роль действует со следующего запроса.")
        return redirect(f"/employees/?id={obj.pk}")
    return render(request, "core/employee_form.html", {"form": form, "employee": employee})


@require_POST
@business_action
def employee_action(request, pk):
    user = request.user
    require(can_manage_users(user))
    employee = get_object_or_404(User, pk=pk)
    action = request.POST.get("action")
    if employee.pk == user.pk and action in ("block", "deactivate"):
        raise BusinessError("Нельзя заблокировать или деактивировать собственную учётную запись.")
    if employee.is_director and not user.is_director:
        raise BusinessError("Учётную запись директора изменяет только директор.")
    old = employee.get_status_display()
    if action == "block":
        employee.status = User.STATUS_BLOCKED
        msg = f"Учётная запись {employee.short_name} заблокирована. Проекты и замечания сохранены."
    elif action == "unblock":
        employee.status = User.STATUS_ACTIVE
        employee.failed_login_attempts = 0
        employee.locked_until = None
        msg = f"Учётная запись {employee.short_name} разблокирована."
    elif action == "deactivate":
        employee.status = User.STATUS_DEACTIVATED
        msg = f"Учётная запись {employee.short_name} деактивирована. Авторство действий сохранено."
    elif action == "reset":
        password = generate_password()
        employee.set_password(password)
        employee.must_change_password = True
        employee.failed_login_attempts = 0
        employee.locked_until = None
        employee.save()
        request.session["temp_password"] = {"email": employee.email, "password": password, "name": employee.short_name}
        audit(user, "access_reset", f"Сброшен доступ сотрудника {employee.short_name}", employee)
        messages.success(request, "Доступ сброшен: выдан новый временный пароль, при входе потребуется его смена.")
        return redirect(f"/employees/?id={employee.pk}")
    else:
        raise BusinessError("Неизвестное действие.")
    employee.save()
    audit(user, "user_status", msg, employee, None, old, employee.get_status_display())
    messages.success(request, msg)
    return redirect(f"/employees/?id={employee.pk}")
