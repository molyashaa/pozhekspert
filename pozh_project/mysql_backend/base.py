"""
Обёртка над стандартным MySQL-бэкендом Django для MariaDB 10.4 из пакета XAMPP.

Django 5.2 рассчитан на MariaDB 10.5+ и использует синтаксис, которого в 10.4 нет
(INSERT ... RETURNING, ALTER TABLE ... RENAME COLUMN / RENAME INDEX). Из-за этого
на 10.4 возникает ошибка 1064 «You have an error in your SQL syntax».
Здесь для старых версий MariaDB возвращается совместимое поведение (как в Django 4.2).
Для MySQL 8 и MariaDB 10.5+ всё работает как в стандартном бэкенде.
"""
from django.db.backends.mysql import base as mysql_base
from django.db.backends.mysql.features import DatabaseFeatures as MySQLDatabaseFeatures
from django.db.backends.mysql.schema import DatabaseSchemaEditor as MySQLSchemaEditor
from django.utils.functional import cached_property


def _old_mariadb(connection):
    return connection.mysql_is_mariadb and connection.mysql_version < (10, 5, 2)


class DatabaseFeatures(MySQLDatabaseFeatures):
    @cached_property
    def minimum_database_version(self):
        if self.connection.mysql_is_mariadb:
            return (10, 4)
        return (8, 0, 11)

    @cached_property
    def can_return_columns_from_insert(self):
        # INSERT ... RETURNING появился только в MariaDB 10.5
        if self.connection.mysql_is_mariadb:
            return self.connection.mysql_version >= (10, 5, 0)
        return False

    @cached_property
    def can_return_rows_from_bulk_insert(self):
        return self.can_return_columns_from_insert

    @cached_property
    def can_rename_index(self):
        # ALTER TABLE ... RENAME INDEX — с MariaDB 10.5.2
        if self.connection.mysql_is_mariadb:
            return self.connection.mysql_version >= (10, 5, 2)
        return True


class DatabaseSchemaEditor(MySQLSchemaEditor):
    @property
    def sql_rename_column(self):
        # ALTER TABLE ... RENAME COLUMN — с MariaDB 10.5.2; раньше только CHANGE
        if _old_mariadb(self.connection):
            return "ALTER TABLE %(table)s CHANGE %(old_column)s %(new_column)s %(type)s"
        return "ALTER TABLE %(table)s RENAME COLUMN %(old_column)s TO %(new_column)s"


class DatabaseWrapper(mysql_base.DatabaseWrapper):
    features_class = DatabaseFeatures
    SchemaEditorClass = DatabaseSchemaEditor
