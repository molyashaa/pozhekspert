"""
Заполнение базы демонстрационными данными учебного прототипа.

    python manage.py seed_demo           — загрузить демо-данные в пустую базу
    python manage.py seed_demo --reset   — удалить ВСЕ данные (кроме ролей) и загрузить заново

Все записи помечены как тестовые (is_demo) и вымышлены: это не сведения ООО «ПожЭксперт+».
Даты рассчитываются от сегодняшнего дня, поэтому сценарии (просрочки, очередь проверок)
выглядят актуально в любой день защиты.
"""
from datetime import date, datetime, time, timedelta
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import (
    AIArchiveEntry, ApprovalPackage, Assignment, AuditLog, Client, Document, DocumentVersion, Notification, Project,
    Remark, RemarkComment, RemarkHistory, Review, Role, Stage, StageDependency, Task, User, ensure_roles,
)

DEMO_DIR = Path(__file__).resolve().parents[2] / "demo_files"
T = date.today()


def d(days):
    return T + timedelta(days=days)


def dt(days, hour=10, minute=0):
    return datetime.combine(d(days), time(hour, minute))


class Command(BaseCommand):
    help = "Загружает демонстрационные данные (сотрудники, клиенты, проекты, этапы, документы, замечания, архив ИИ)"

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Удалить все данные (кроме ролей) перед загрузкой")

    def handle(self, *args, **options):
        ensure_roles()
        if options["reset"]:
            self.wipe()
        elif User.objects.filter(is_demo=True).exists():
            self.stdout.write(self.style.WARNING(
                "Демо-данные уже загружены. Для перезагрузки: python manage.py seed_demo --reset"))
            return
        with transaction.atomic():
            self.create_all()
        self.stdout.write(self.style.SUCCESS(
            f"Готово. Демо-пароль для всех учётных записей: {settings.DEMO_PASSWORD}\n"
            "Директор: smirnova@pozhexpert.example · ГИП: sokolov@pozhexpert.example · "
            "Проектировщик: petrov@pozhexpert.example · Эксперт: gromov@pozhexpert.example"))

    # ------------------------------------------------------------------
    def wipe(self):
        self.stdout.write("Удаление существующих данных…")
        with transaction.atomic():
            for model in (Notification, AuditLog, RemarkComment, RemarkHistory):
                model.objects.all().delete()
            AIArchiveEntry.objects.all().delete()
            Remark.objects.all().delete()
            Review.objects.all().delete()
            ApprovalPackage.objects.all().delete()
            DocumentVersion.objects.all().delete()
            Document.objects.all().delete()
            Assignment.objects.all().delete()
            Task.objects.all().delete()
            StageDependency.objects.all().delete()
            Stage.objects.all().delete()
            Project.objects.all().delete()
            Client.objects.all().delete()
            User.objects.filter(is_superuser=False).delete()
            User.objects.filter(is_demo=True).delete()

    # ------------------------------------------------------------------
    def create_all(self):
        R = {r.code: r for r in Role.objects.all()}
        pwd = settings.DEMO_PASSWORD

        def user(email, name, role, dept="", **extra):
            u = User(email=f"{email}@pozhexpert.example", full_name=name, role=R[role], department=dept, is_demo=True,
                     **extra)
            u.set_password(pwd)
            u.save()
            return u

        self.u = U = {
            "smirnova": user("smirnova", "Смирнова Елена Викторовна", Role.DIRECTOR, "Руководство",
                             can_manage_users=True, can_manage_clients=True, is_staff=True, is_superuser=True),
            "sokolov": user("sokolov", "Соколов Олег Валерьевич", Role.GIP, "Отдел ГИП"),
            "lebedeva": user("lebedeva", "Лебедева Ирина Андреевна", Role.GIP, "Отдел ГИП"),
            "petrov": user("petrov", "Петров Алексей Сергеевич", Role.DESIGNER, "Проектный отдел"),
            "orlov": user("orlov", "Орлов Дмитрий Игоревич", Role.DESIGNER, "Проектный отдел"),
            "frolov": user("frolov", "Фролов Николай Павлович", Role.DESIGNER, "Проектный отдел"),
            "kozlova": user("kozlova", "Козлова Мария Николаевна", Role.CALCULATOR, "Расчётный отдел"),
            "gromov": user("gromov", "Громов Виктор Константинович", Role.EXPERT, "Отдел внутренней экспертизы"),
            "zaitseva": user("zaitseva", "Зайцева Ольга Петровна", Role.EXPERT, "Отдел внутренней экспертизы"),
            "belova": user("belova", "Белова Татьяна Романовна", Role.ESTIMATOR, "Сметный отдел"),
            "yakovleva": user("yakovleva", "Яковлева Анна Дмитриевна", Role.APPROVAL, "Отдел согласований"),
            "nikolaev": user("nikolaev", "Николаев Павел Романович", Role.DESIGNER, "Проектный отдел",
                             status=User.STATUS_DEACTIVATED),
        }
        last = {"smirnova": (0, 8, 55), "sokolov": (0, 9, 2), "lebedeva": (-1, 18, 10), "petrov": (0, 8, 40),
                "orlov": (0, 9, 8), "kozlova": (0, 9, 12), "gromov": (0, 8, 50), "belova": (-1, 16, 20),
                "yakovleva": (-2, 11, 30), "nikolaev": (-60, 17, 45), "frolov": (-1, 9, 30), "zaitseva": (0, 9, 40)}
        for key, (days, h, m) in last.items():
            User.objects.filter(pk=U[key].pk).update(last_login=dt(days, h, m), created_at=dt(-300 + days))

        director = U["smirnova"]

        def client(name, contact, phone, email, address, inn="", ctype="org", status="active"):
            return Client.objects.create(
                name=name, contact_person=contact, phone=phone, email=email, address=address, inn=inn,
                client_type=ctype, status=status, is_demo=True, created_by=director, updated_by=director,
                source="Демонстрационная запись учебного прототипа (вымышленные данные)")

        C = {
            "sever": client("ООО «Север-Логистика»", "Иванов Пётр Андреевич", "+7 (900) 000-11-22",
                            "info@sever-logistika.example", "Владимирская обл., г. Александров, ул. Складская, 4",
                            "3300000011"),
            "passage": client("ООО «Пассаж-Девелопмент»", "Морозова Светлана Игоревна", "+7 (900) 000-33-44",
                              "office@passage.example", "г. Александров, ул. Центральная, 12", "3300000022"),
            "school": client("МБОУ «Школа № 3» (демо)", "Кузнецова Наталья Олеговна", "+7 (900) 000-55-66",
                             "school3@edu.example", "г. Александров, ул. Школьная, 3"),
            "karpov": client("ИП Карпов Андрей Викторович", "Карпов Андрей Викторович", "+7 (900) 000-77-88",
                             "karpov@mail.example", "г. Струнино, ул. Заводская, 7", ctype="person"),
            "agro": client("ООО «АгроТех»", "Сидоров Илья Маркович", "+7 (900) 000-99-00", "agro@agrotech.example",
                           "Александровский р-н, д. Новинки", "3300000033", status="archived"),
        }

        # ------------------------------------------------------------------
        # Проект 1 — Склад «Север» (как на макетах: 9 этапов, 5 принято, 1 на проверке, 1 на доработке, 2 блок.)
        # ------------------------------------------------------------------
        p1 = self.project("ПБ-2026-011", "Склад «Север»", C["sever"], U["sokolov"], -80, 30, Project.IN_PROGRESS,
                          "Складской комплекс класса В, 2 зоны хранения, экспедиция, АБК",
                          "Разработка разделов пожарной безопасности: расчёт категорий, эвакуации, АПС, СОУЭ, "
                          "водяное пожаротушение, спецификации, смета и итоговый комплект.", U["yakovleva"])
        S = {}
        S[1] = self.stage(p1, 1, "Расчёт категорий помещений", Role.CALCULATOR, U["kozlova"], U["gromov"], -78, -55,
                          Stage.ACCEPTED, 40, actual=(-78, -56))
        S[2] = self.stage(p1, 2, "Расчёт эвакуации", Role.CALCULATOR, U["kozlova"], U["gromov"], -55, -40,
                          Stage.ACCEPTED, 32, deps=[S[1]], actual=(-55, -41))
        S[3] = self.stage(p1, 3, "Схема АПС", Role.DESIGNER, U["petrov"], U["gromov"], -55, -30, Stage.ACCEPTED, 48,
                          deps=[S[1]], actual=(-55, -31))
        S[4] = self.stage(p1, 4, "Схема СОУЭ", Role.DESIGNER, U["orlov"], U["gromov"], -40, -22, Stage.ACCEPTED, 32,
                          deps=[S[2]], actual=(-40, -23))
        S[5] = self.stage(p1, 5, "Планы расположения оборудования", Role.DESIGNER, U["petrov"], U["gromov"], -22, -15,
                          Stage.ACCEPTED, 24, deps=[S[3], S[4]], actual=(-22, -16))
        S[6] = self.stage(p1, 6, "Схема водяного пожаротушения", Role.DESIGNER, U["orlov"], U["gromov"], -38, 0,
                          Stage.ON_REVIEW, 56, deps=[S[2]], actual=(-38, None))
        S[7] = self.stage(p1, 7, "Узлы управления и спецификации", Role.DESIGNER, U["petrov"], U["gromov"], -28, -5,
                          Stage.REWORK, 40, deps=[S[3]], actual=(-28, None),
                          expected="Спецификация оборудования АПС и СОУЭ")
        S[8] = self.stage(p1, 8, "Смета", Role.ESTIMATOR, U["belova"], U["gromov"], 1, 12, Stage.BLOCKED, 24,
                          deps=[S[7]])
        S[9] = self.stage(p1, 9, "Пояснительная записка и итоговый комплект", Role.DESIGNER, None, None, 5, 22,
                          Stage.BLOCKED, 24, deps=[S[6], S[7]])

        src = self.doc(p1, None, "source", "Задание заказчика на проектирование", U["sokolov"])
        self.version(src, 1, "source_task.pdf", "Задание_заказчика_Склад_Север.pdf", U["sokolov"],
                     DocumentVersion.ACCEPTED, "Получено от заказчика вместе с заявкой", -80)
        tc = self.doc(p1, None, "source", "Технические условия на водоснабжение", U["sokolov"])
        self.version(tc, 1, "tech_conditions.docx", "ТУ_водоснабжение.docx", U["sokolov"], DocumentVersion.ACCEPTED,
                     "Исходные данные", -79)
        plan = self.doc(p1, None, "drawing", "Поэтажный план (подложка)", U["sokolov"])
        self.version(plan, 1, "plan_floor1.dxf", "План_1_этажа.dxf", U["sokolov"], DocumentVersion.ACCEPTED,
                     "Подложка для разработки схем", -79)

        g = U["gromov"]
        d1 = self.doc(p1, S[1], "calculation", "Расчёт категорий помещений", U["kozlova"])
        v = self.version(d1, 1, "categories_calc.pdf", "Расчёт_категорий_v1.pdf", U["kozlova"],
                         DocumentVersion.ACCEPTED, "Расчёт по составу пожарной нагрузки", -60)
        self.review(S[1], g, "accepted", [v], -56, "Расчёт корректен")
        d2 = self.doc(p1, S[2], "calculation", "Расчёт времени эвакуации", U["kozlova"])
        v = self.version(d2, 1, "evacuation_calc.pdf", "Расчёт_эвакуации.pdf", U["kozlova"], DocumentVersion.ACCEPTED,
                         "Расчёт по двум сценариям", -43)
        self.review(S[2], g, "accepted", [v], -41)

        d3 = self.doc(p1, S[3], "scheme", "Схема АПС", U["petrov"])
        v1 = self.version(d3, 1, "aps_scheme_v1.pdf", "Схема_АПС_v1.pdf", U["petrov"], DocumentVersion.RETURNED,
                          "Первая версия схемы", -36)
        rv = self.review(S[3], g, "returned", [v1], -34, "Нужно уточнить зоны контроля")
        r19 = self.remark("Р-019", S[3], v1, g, U["petrov"], "Лист 2",
                          "Не указаны зоны контроля пожарной сигнализации для помещения экспедиции.",
                          "significant", -34, Remark.ACCEPTED, review=rv, due=-31, resolved=-31,
                          category="Неполнота схемы")
        v2 = self.version(d3, 2, "aps_scheme_v2.pdf", "Схема_АПС_v2.pdf", U["petrov"], DocumentVersion.ACCEPTED,
                          "Добавлены зоны контроля по замечанию Р-019", -32)
        r19.fixed_in_version = v2
        r19.ai_status = "candidate"
        r19.save()
        self.review(S[3], g, "accepted", [v2], -31)

        d4 = self.doc(p1, S[4], "scheme", "Схема СОУЭ", U["orlov"])
        v = self.version(d4, 1, "soue_scheme.pdf", "Схема_СОУЭ.pdf", U["orlov"], DocumentVersion.ACCEPTED,
                         "Схема оповещения 2-го типа", -25)
        self.review(S[4], g, "accepted", [v], -23)
        d5 = self.doc(p1, S[5], "drawing", "Планы расположения оборудования", U["petrov"])
        v = self.version(d5, 1, "plans.pdf", "Планы_оборудования.pdf", U["petrov"], DocumentVersion.ACCEPTED,
                         "Планы 1 и 2 этажа", -17)
        self.review(S[5], g, "accepted", [v], -16)

        # этап 6 — на проверке (версия 2 передана сегодня), исправленные замечания Р-027, Р-028
        d6 = self.doc(p1, S[6], "scheme", "Схема водяного пожаротушения", U["orlov"])
        v1 = self.version(d6, 1, "water_scheme_v1.pdf", "Схема_ВПТ_v1.pdf", U["orlov"], DocumentVersion.RETURNED,
                          "Первая версия", -6)
        rv = self.review(S[6], g, "returned", [v1], -4, "Требуются уточнения по магистрали")
        v2 = self.version(d6, 2, "water_scheme_v2.pdf", "Схема_ВПТ_v2.pdf", U["orlov"], DocumentVersion.SUBMITTED,
                          "Указан диаметр магистрали, добавлена насосная станция в экспликацию", 0, hour=9)
        for num, section, text, sev in (
            ("Р-027", "Схема, лист 2", "На схеме не указан диаметр магистрального трубопровода.", "significant"),
            ("Р-028", "Схема, лист 1", "Нет обозначения насосной станции в экспликации.", "minor"),
        ):
            r = self.remark(num, S[6], v1, g, U["orlov"], section, text, sev, -4, Remark.FIXED, review=rv, due=-1,
                            category="Неполнота схемы")
            r.fixed_in_version = v2
            r.save()
        Stage.objects.filter(pk=S[6].pk).update(submitted_at=dt(0, 9, 5))

        # этап 7 — возвращён на доработку, срок просрочен на 5 дней
        d7 = self.doc(p1, S[7], "specification", "Спецификация оборудования", U["petrov"])
        v1 = self.version(d7, 1, "spec_v1.pdf", "Спецификация_v1.pdf", U["petrov"], DocumentVersion.RETURNED,
                          "Спецификация АПС и СОУЭ", -9)
        rv = self.review(S[7], g, "returned", [v1], -7, "Критическое замечание по категории помещения")
        self.remark("Р-031", S[7], v1, g, U["petrov"], "Раздел 3.2, лист 5",
                    "Не указана категория помещения по пожарной опасности для зоны хранения.", "critical", -7,
                    Remark.OPEN, review=rv, due=0, category="Нормативные требования")
        self.remark("Р-032", S[7], v1, g, U["petrov"], "Лист 7",
                    "Номенклатура извещателей в спецификации не совпадает со схемой АПС (этап 3).", "significant", -7,
                    Remark.OPEN, review=rv, due=0, category="Расхождение разделов")
        Task.objects.create(stage=S[7], title="Сверить спецификацию со схемой АПС", executor=U["petrov"],
                            status="in_progress", deadline=d(1), labor_hours=6, created_by=U["sokolov"])

        # внешнее замечание согласующей стороны по СОУЭ
        self.remark("Р-035", S[4], None, U["yakovleva"], U["orlov"], "Пояснительная часть схемы",
                    "Согласующая сторона просит обосновать выбор 2-го типа СОУЭ для складской зоны.", "significant",
                    -2, Remark.OPEN, due=7, source="external", document=d4,
                    category="Замечание согласующей стороны")

        pkg = ApprovalPackage.objects.create(project=p1, title="Разделы АПС и СОУЭ для согласования",
                                             authority="Надзорный орган (МЧС), демо", status="preparing",
                                             created_by=U["yakovleva"])
        pkg.documents.set([d3, d4, d5])

        # ------------------------------------------------------------------
        # Проект 2 — ТЦ «Пассаж»: просроченный расчёт, этап «Согласование» без файла
        # ------------------------------------------------------------------
        p2 = self.project("ПБ-2026-017", "ТЦ «Пассаж»", C["passage"], U["sokolov"], -40, 45, Project.IN_PROGRESS,
                          "Торговый центр, 3 этажа, г. Александров",
                          "Расчёт пожарного риска и проект АУПТ для торгового центра.", U["yakovleva"])
        s21 = self.stage(p2, 1, "Обследование и исходные данные", Role.DESIGNER, U["frolov"], U["zaitseva"], -40, -30,
                         Stage.ACCEPTED, 16, actual=(-40, -31))
        s22 = self.stage(p2, 2, "Расчёт пожарного риска", Role.CALCULATOR, U["kozlova"], U["gromov"], -30, -3,
                         Stage.IN_PROGRESS, 60, deps=[s21], actual=(-30, None))
        s23 = self.stage(p2, 3, "Схема АУПТ", Role.DESIGNER, U["frolov"], U["gromov"], -2, 25, Stage.BLOCKED, 64,
                         deps=[s22])
        self.stage(p2, 4, "Согласование", Role.APPROVAL, U["yakovleva"], U["sokolov"], 25, 40, Stage.BLOCKED, 8,
                   deps=[s23], file_required=False)
        dd = self.doc(p2, s21, "source", "Акт обследования объекта", U["frolov"])
        v = self.version(dd, 1, "source_task.pdf", "Акт_обследования.pdf", U["frolov"], DocumentVersion.ACCEPTED,
                         "Результаты обследования", -32)
        self.review(s21, U["zaitseva"], "accepted", [v], -31)

        # ------------------------------------------------------------------
        # Проект 3 — Школа № 3: параллельные этапы, расчёт на проверке у второго эксперта
        # ------------------------------------------------------------------
        p3 = self.project("ПБ-2026-021", "Школа № 3, корпус Б", C["school"], U["lebedeva"], -20, 60,
                          Project.IN_PROGRESS, "г. Александров, ул. Школьная, 3, корпус Б",
                          "Модернизация АПС и СОУЭ учебного корпуса.", None)
        s31 = self.stage(p3, 1, "Расчёт категорий помещений", Role.CALCULATOR, U["kozlova"], U["zaitseva"], -20, 2,
                         Stage.ON_REVIEW, 24, actual=(-20, None))
        s32 = self.stage(p3, 2, "Схема АПС", Role.DESIGNER, U["petrov"], U["zaitseva"], -15, 6, Stage.IN_PROGRESS, 40,
                         actual=(-15, None))
        self.stage(p3, 3, "Схема СОУЭ", Role.DESIGNER, U["frolov"], U["zaitseva"], -15, 9, Stage.IN_PROGRESS, 32,
                   actual=(-15, None))
        self.stage(p3, 4, "Спецификации и смета", Role.ESTIMATOR, U["belova"], U["zaitseva"], 9, 30, Stage.BLOCKED, 24,
                   deps=[s31, s32])
        dd = self.doc(p3, s31, "calculation", "Расчёт категорий помещений корпуса Б", U["kozlova"])
        self.version(dd, 1, "categories_calc.pdf", "Расчёт_категорий_корпус_Б.pdf", U["kozlova"],
                     DocumentVersion.SUBMITTED, "Расчёт для учебных и вспомогательных помещений", -1, hour=17)
        Stage.objects.filter(pk=s31.pk).update(submitted_at=dt(-1, 17, 10))
        for title, days, hours in (("Разместить извещатели: 1 этаж", 2, 8), ("Разместить извещатели: 2 этаж", 4, 8),
                                   ("Кабельный журнал", 6, None)):
            Task.objects.create(stage=s32, title=title, executor=U["petrov"], status="todo", deadline=d(days),
                                labor_hours=hours, created_by=U["lebedeva"])

        # ------------------------------------------------------------------
        # Проект 4 — черновик; Проект 5 — завершён (клиент в архиве)
        # ------------------------------------------------------------------
        p4 = self.project("ПБ-2026-024", "Офис «Меридиан»", C["karpov"], U["sokolov"], 7, 70, Project.DRAFT,
                          "г. Струнино, ул. Заводская, 7", "Проект АПС офисного здания. Ожидает запуска.", None)
        a1 = self.stage(p4, 1, "Расчёт категорий помещений", Role.CALCULATOR, U["kozlova"], U["gromov"], 7, 20,
                        Stage.NOT_STARTED, 16)
        self.stage(p4, 2, "Схема АПС", Role.DESIGNER, None, None, 20, 45, Stage.NOT_STARTED, 32, deps=[a1])

        p5 = self.project("ПБ-2025-008", "Ангар «АгроТех»", C["agro"], U["lebedeva"], -200, -60, Project.COMPLETED,
                          "Александровский р-н, д. Новинки", "Завершённый проект (архивный клиент).", U["yakovleva"])
        Project.objects.filter(pk=p5.pk).update(actual_end_date=d(-62))
        prev = None
        for i, (name, role, ex) in enumerate((("Расчёт категорий помещений", Role.CALCULATOR, U["kozlova"]),
                                              ("Схема АПС", Role.DESIGNER, U["orlov"]),
                                              ("Пояснительная записка", Role.DESIGNER, U["orlov"])), 1):
            st = self.stage(p5, i, name, role, ex, U["gromov"], -200 + i * 40, -170 + i * 35, Stage.ACCEPTED, 24,
                            deps=[prev] if prev else None, actual=(-200 + i * 40, -172 + i * 35))
            dd = self.doc(p5, st, "explanatory" if i == 3 else ("calculation" if i == 1 else "scheme"), name, ex)
            v = self.version(dd, 1, "explanatory.pdf" if i == 3 else ("categories_calc.pdf" if i == 1 else
                                                                        "aps_scheme_v2.pdf"),
                             f"{name}.pdf", ex, DocumentVersion.ACCEPTED, "Итоговая версия", -175 + i * 35)
            self.review(st, U["gromov"], "accepted", [v], -172 + i * 35)
            prev = st
        pk5 = ApprovalPackage.objects.create(project=p5, title="Итоговый комплект", authority="Надзорный орган (МЧС), демо",
                                             status="approved", sent_date=d(-90), response_date=d(-70),
                                             response_note="Согласовано без замечаний (демо)",
                                             created_by=U["yakovleva"])
        pk5.documents.set(Document.objects.filter(project=p5))
        est = self.doc(p1, S[8], "estimate", "Смета на монтаж (черновик)", U["belova"])
        self.version(est, 1, "estimate.xlsx", "Смета_черновик.xlsx", U["belova"], DocumentVersion.DRAFT,
                     "Заготовка сметы до принятия спецификации", -1)

        self.ai_archive()
        self.history(p1, p2, p3, p4, S, U)
        self.notifications(U, p1, p3, S)

    # ------------------------------------------------------------------
    def project(self, number, name, client, gip, start, end, status, address, description, approval):
        p = Project.objects.create(number=number, name=name, client=client, gip=gip, start_date=d(start),
                                   planned_end_date=d(end), status=status, object_address=address,
                                   description=description, approval_manager=approval, is_demo=True,
                                   created_by=gip)
        Project.objects.filter(pk=p.pk).update(created_at=dt(start - 2))
        return p

    def stage(self, project, no, name, role, executor, reviewer, start, deadline, status, hours, deps=None,
              actual=None, file_required=True, expected=""):
        st = Stage.objects.create(
            project=project, sequence_no=no, name=name, executor_role=Role.objects.get(code=role), executor=executor,
            reviewer=reviewer, start_date=d(start), deadline=d(deadline), status=status, labor_hours=hours,
            file_required=file_required, expected_result=expected or name,
            actual_start=d(actual[0]) if actual and actual[0] is not None else None,
            actual_end=d(actual[1]) if actual and actual[1] is not None else None,
        )
        for dep in deps or []:
            StageDependency.objects.create(stage=st, depends_on=dep)
        if executor:
            Assignment.objects.create(stage=st, user=executor, role_in_task="executor", assigned_by=project.gip)
        if reviewer:
            Assignment.objects.create(stage=st, user=reviewer, role_in_task="reviewer", assigned_by=project.gip)
        Assignment.objects.filter(stage=st).update(created_at=dt(start - 1))
        return st

    def doc(self, project, stage, doc_type, title, author):
        return Document.objects.create(project=project, stage=stage, doc_type=doc_type, title=title,
                                       created_by=author, current_version_no=0)

    def version(self, doc, no, filename, display, author, status, comment, days, hour=11):
        path = DEMO_DIR / filename
        v = DocumentVersion(document=doc, version_no=no, original_name=display,
                            extension=filename.rsplit(".", 1)[1], size=path.stat().st_size, comment=comment,
                            review_status=status, uploaded_by=author)
        with open(path, "rb") as fh:
            v.file.save(filename, File(fh), save=False)
        v.save()
        DocumentVersion.objects.filter(pk=v.pk).update(uploaded_at=dt(days, hour))
        Document.objects.filter(pk=doc.pk).update(current_version_no=no, updated_at=dt(days, hour))
        doc.current_version_no = no
        return v

    def review(self, stage, reviewer, decision, versions, days, comment=""):
        r = Review.objects.create(stage=stage, reviewer=reviewer, decision=decision, comment=comment)
        r.versions.set(versions)
        Review.objects.filter(pk=r.pk).update(created_at=dt(days, 15))
        return r

    def remark(self, number, stage, version, author, assignee, section, text, severity, days, status, review=None,
               due=None, resolved=None, source="internal", document=None, category=""):
        r = Remark.objects.create(
            number=number, project=stage.project, stage=stage, version=version,
            document=version.document if version else document, section=section, text=text, severity=severity,
            author=author, assignee=assignee, status=status, review=review, source=source, category=category,
            due_date=d(due) if due is not None else None,
            resolved_at=dt(resolved, 15) if resolved is not None else None,
        )
        Remark.objects.filter(pk=r.pk).update(created_at=dt(days, 15))
        RemarkHistory.objects.create(remark=r, old_status="", new_status=Remark.OPEN, user=author,
                                     comment="Замечание создано")
        if status in (Remark.FIXED, Remark.ACCEPTED):
            RemarkHistory.objects.create(remark=r, old_status=Remark.OPEN, new_status=Remark.FIXED, user=assignee,
                                         comment="Исполнитель передал исправленный результат")
        if status == Remark.ACCEPTED:
            RemarkHistory.objects.create(remark=r, old_status=Remark.FIXED, new_status=Remark.ACCEPTED, user=author,
                                         comment="Исправление принято")
        return r

    # ------------------------------------------------------------------
    def ai_archive(self):
        """Вручную подготовленные демонстрационные типовые примеры (не записи ООО «ПожЭксперт+»)."""
        examples = [
            ("Спецификация не соответствует схеме", "Количество и типы дымовых извещателей в спецификации не совпадают "
             "с обозначениями на схеме АПС.", "Расхождение разделов", "Схема АПС", "specification",
             "Сверили спецификацию со схемой по каждой позиции и загрузили исправленную версию с комментарием.", -250),
            ("Расхождение между разделами документации", "Тип оборудования в пояснительной записке указан иначе, чем на "
             "схеме.", "Расхождение разделов", "Пояснительная записка", "explanatory",
             "Согласовали обозначения между разделами и добавили перечень условных обозначений.", -170),
            ("Неполная спецификация", "В спецификации отсутствуют позиции кабельной продукции, показанные на плане.",
             "Неполнота документации", "Спецификации", "specification",
             "Дополнили спецификацию недостающими позициями и пересчитали количество.", -360),
            ("Не указана категория помещения", "Для складского помещения не указана категория по взрывопожарной и "
             "пожарной опасности.", "Нормативные требования", "Расчёт категорий помещений", "calculation",
             "Выполнили расчёт пожарной нагрузки и указали категорию В1–В4 в спецификации и на планах.", -300),
            ("Не обоснован тип СОУЭ", "Тип системы оповещения и управления эвакуацией выбран без ссылки на таблицу "
             "требований свода правил.", "Нормативные требования", "Схема СОУЭ", "scheme",
             "Добавили обоснование типа СОУЭ со ссылкой на таблицу нормативного документа.", -200),
            ("Превышено расстояние между извещателями", "Расстояние между точечными дымовыми извещателями превышает "
             "допустимое для высоты помещения.", "Ошибка размещения", "Схема АПС", "scheme",
             "Пересчитали шаг установки извещателей и добавили недостающие извещатели на плане.", -280),
            ("Не показаны зоны контроля", "На схеме АПС не обозначены зоны контроля пожарной сигнализации.",
             "Неполнота схемы", "Схема АПС", "scheme", "Обозначили зоны контроля и номера шлейфов на листах схемы.",
             -150),
            ("Ручные извещатели не на путях эвакуации", "Ручные пожарные извещатели размещены не у выходов и не на "
             "путях эвакуации.", "Ошибка размещения", "Планы расположения оборудования", "drawing",
             "Перенесли ручные извещатели к эвакуационным выходам на высоту по требованиям.", -230),
            ("Не указан диаметр трубопровода", "На схеме водяного пожаротушения не указан диаметр магистрального и "
             "распределительных трубопроводов.", "Неполнота схемы", "Схема водяного пожаротушения", "scheme",
             "Указали диаметры по гидравлическому расчёту на всех участках схемы.", -190),
            ("Нет насосной станции в экспликации", "Помещение насосной станции пожаротушения отсутствует в экспликации "
             "помещений.", "Неполнота схемы", "Схема водяного пожаротушения", "scheme",
             "Добавили насосную станцию в экспликацию и на план с обозначением.", -185),
            ("Гидравлический расчёт не приложен", "Расход и напор для АУПТ указаны без гидравлического расчёта.",
             "Обоснование решений", "Схема АУПТ", "calculation",
             "Выполнили гидравлический расчёт и приложили его к разделу.", -320),
            ("Время эвакуации без учёта задержки", "В расчёте времени эвакуации не учтено время начала эвакуации.",
             "Ошибка расчёта", "Расчёт эвакуации", "calculation",
             "Пересчитали время с учётом задержки начала эвакуации по методике.", -210),
            ("Ширина эвакуационного выхода", "Ширина эвакуационного выхода меньше требуемой для расчётного числа людей.",
             "Нормативные требования", "Расчёт эвакуации", "drawing",
             "Увеличили ширину выхода на плане, обновили расчёт эвакуации.", -260),
            ("Огнестойкость кабеля не указана", "В спецификации не указан тип огнестойкого кабеля для линий СОУЭ.",
             "Неполнота документации", "Спецификации", "specification",
             "Указали марку огнестойкого кабеля и исполнение по требованиям к линиям СОУЭ.", -140),
            ("Не указано резервное питание", "Для приборов АПС не указан источник резервного питания и время работы.",
             "Неполнота документации", "Схема АПС", "scheme",
             "Добавили расчёт ёмкости аккумуляторов и резервный источник питания на схему.", -175),
            ("Оповещатели не обеспечивают слышимость", "Количество звуковых оповещателей недостаточно для требуемого "
             "уровня звука в складской зоне.", "Ошибка расчёта", "Схема СОУЭ", "scheme",
             "Выполнили расчёт звукового давления и добавили оповещатели.", -160),
            ("Световые табло «Выход» отсутствуют", "На плане не показаны световые оповещатели «Выход» над "
             "эвакуационными выходами.", "Неполнота схемы", "Схема СОУЭ", "drawing",
             "Добавили табло «Выход» над всеми эвакуационными выходами.", -155),
            ("Смета не соответствует спецификации", "Количество оборудования в смете отличается от спецификации.",
             "Расхождение разделов", "Смета", "estimate",
             "Привели смету в соответствие со спецификацией и пересчитали итог.", -130),
            ("Не учтены пусконаладочные работы", "В смете отсутствуют пусконаладочные работы по системам "
             "противопожарной защиты.", "Неполнота документации", "Смета", "estimate",
             "Добавили позиции пусконаладки по каждой системе.", -125),
            ("Неверный масштаб плана", "Масштаб на плане не соответствует указанному в штампе, размеры не читаются.",
             "Оформление", "Планы расположения оборудования", "drawing",
             "Исправили масштаб листов и обновили штамп.", -120),
            ("Нет ссылки на нормативный документ", "В пояснительной записке решения приведены без ссылок на пункты "
             "нормативных документов.", "Обоснование решений", "Пояснительная записка", "explanatory",
             "Добавили ссылки на пункты сводов правил для каждого решения.", -110),
            ("Противопожарный клапан не показан", "На схеме вентиляции не показаны противопожарные нормально открытые "
             "клапаны на границе пожарного отсека.", "Неполнота схемы", "Противодымная вентиляция", "scheme",
             "Добавили клапаны и указали их управление от системы АПС.", -100),
            ("Не указан алгоритм управления", "Не описан алгоритм формирования сигналов управления СОУЭ и "
             "инженерными системами при срабатывании АПС.", "Обоснование решений", "Схема АПС", "explanatory",
             "Описали алгоритм управления и привели таблицу сигналов.", -95),
            ("Ошибка в экспликации помещений", "Номера помещений в экспликации не совпадают с номерами на плане.",
             "Оформление", "Планы расположения оборудования", "drawing",
             "Сверили номера и исправили экспликацию на всех листах.", -90),
        ]
        director = self.u["smirnova"]
        expert = self.u["gromov"]
        for title, text, cat, stage_type, doc_type, resolution, days in examples:
            e = AIArchiveEntry(title=title, text=text, category=cat, stage_type=stage_type, doc_type=doc_type,
                               resolution=resolution, record_date=d(days), status=AIArchiveEntry.INCLUDED,
                               is_demo=True, source_label="Демо-архив (подготовленный пример)", created_by=director,
                               checked_by=expert)
            e.checked_at = dt(-30)
            e.indexed_at = dt(-30)
            e.save()
        # пример исключённой записи и кандидата
        e = AIArchiveEntry(title="Неудачная формулировка", text="Исправить схему.", category="Прочее",
                           status=AIArchiveEntry.EXCLUDED, is_demo=True, source_label="Демо-архив",
                           created_by=director, checked_by=expert)
        e.checked_at = dt(-20)
        e.save()

    def history(self, p1, p2, p3, p4, S, U):
        events = [
            (-82, U["smirnova"], "user_created", "Создана учётная запись Козлова М. Н., роль «Расчётчик»", None),
            (-82, U["sokolov"], "project_created", "Создан проект ПБ-2026-011 «Склад «Север»»", p1),
            (-81, U["sokolov"], "project_launched", "Проект ПБ-2026-011 запущен в работу", p1),
            (-56, U["gromov"], "stage_accepted", "Принят результат этапа 1 «Расчёт категорий помещений»", p1),
            (-34, U["gromov"], "stage_returned", "Этап 3 «Схема АПС» возвращён на доработку (замечание Р-019)", p1),
            (-31, U["gromov"], "stage_accepted", "Принят результат этапа 3 «Схема АПС» (версия 2)", p1),
            (-16, U["gromov"], "stage_accepted", "Принят результат этапа 5 «Планы расположения оборудования»", p1),
            (-9, U["sokolov"], "deadline_changed", "Перенесён срок этапа 6 «Схема водяного пожаротушения». "
                                                   "Причина: уточнение технических условий", p1),
            (-7, U["gromov"], "stage_returned", "Этап 7 «Узлы управления и спецификации» возвращён на доработку", p1),
            (-2, U["yakovleva"], "remark_created", "Зарегистрировано замечание согласующей стороны Р-035", p1),
            (-1, U["kozlova"], "stage_submitted", "Этап 1 «Расчёт категорий помещений» передан на проверку", p3),
            (-1, U["smirnova"], "user_status", "Учётная запись Николаев П. Р. деактивирована", None),
            (0, U["orlov"], "version_uploaded", "Загружена версия 2 документа «Схема водяного пожаротушения»", p1),
            (0, U["orlov"], "stage_submitted", "Этап 6 «Схема водяного пожаротушения» передан на проверку", p1),
        ]
        for days, user, action, desc, project in events:
            AuditLog.objects.create(user=user, action=action, description=desc, project=project,
                                    created_at=dt(days, 9 if days == 0 else 14, 5))
        AuditLog.objects.create(user=U["sokolov"], action="project_created", project=p4,
                                description="Создан проект ПБ-2026-024 «Офис «Меридиан»» (черновик)", created_at=dt(-3))

    def notifications(self, U, p1, p3, S):
        items = [
            (U["gromov"], "submitted", "Результат на проверке: Схема водяного пожаротушения",
             f"/stages/{S[6].pk}/review/", p1, 0),
            (U["petrov"], "returned", "Возвращено на доработку: Узлы управления и спецификации",
             f"/stages/{S[7].pk}/", p1, -7),
            (U["petrov"], "overdue", "Просрочен срок этапа «Узлы управления и спецификации»", f"/stages/{S[7].pk}/", p1,
             -4),
            (U["orlov"], "remark", "Новое замечание Р-035 (согласующая сторона)", "/remarks/", p1, -2),
            (U["sokolov"], "submitted", "Этап 6 передан на проверку эксперту Громову В. К.", f"/projects/{p1.pk}/", p1, 0),
            (U["sokolov"], "overdue", "Этап 7 «Узлы управления и спецификации» просрочен на 5 дней",
             f"/stages/{S[7].pk}/", p1, -1),
            (U["smirnova"], "system", "Добро пожаловать в демо-версию «ПожЭксперт+»", "/", None, -1),
        ]
        for user, kind, title, url, project, days in items:
            n = Notification.objects.create(user=user, event_type=kind, title=title, url=url, project=project)
            Notification.objects.filter(pk=n.pk).update(created_at=dt(days, 9, 10))
