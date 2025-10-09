import ast
import re
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class CODEStatistics(BaseModel):
    """Статистика анализа кода Python"""

    length: Optional[int] = Field(default=None, description="Длина кода")

    defined_variables: Optional[List[str]] = Field(
        default=None, description="Список определенных переменных"
    )
    defined_functions: Optional[List[str]] = Field(
        default=None, description="Список определенных функций"
    )
    used_names: Optional[List[str]] = Field(
        default=None, description="Список использованных имен"
    )
    unused_variables: Optional[List[str]] = Field(
        default=None, description="Список неиспользованных переменных"
    )
    unused_functions: Optional[List[str]] = Field(
        default=None, description="Список неиспользованных функций"
    )
    total_unused: Optional[int] = Field(
        default=None, description="Общее количество неиспользованных элементов"
    )

    class Config:
        extra = "allow"

    @classmethod
    def from_text(cls, code: str):
        """Создает статистику из текста кода"""
        try:
            tree = ast.parse(code)

            # Собираем все определения
            defined_vars = set()
            defined_funcs = set()
            used_names = set()
            imports = set()

            # Анализируем AST
            for node in ast.walk(tree):
                # Собираем определенные переменные
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            defined_vars.add(target.id)

                # Собираем определенные функции
                elif isinstance(node, ast.FunctionDef):
                    defined_funcs.add(node.name)

                # Собираем использованные имена
                elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                    used_names.add(node.id)

                # Собираем импорты
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.add(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        imports.add(node.module)

            # Исключаем импорты из определенных переменных
            defined_vars = defined_vars - imports

            # Находим неиспользуемые элементы
            unused_vars = defined_vars - used_names
            unused_funcs = defined_funcs - used_names

            return cls(
                length=len(code),
                defined_variables=sorted(list(defined_vars)),
                defined_functions=sorted(list(defined_funcs)),
                used_names=sorted(list(used_names)),
                unused_variables=sorted(list(unused_vars)),
                unused_functions=sorted(list(unused_funcs)),
                total_unused=len(unused_vars) + len(unused_funcs),
            )

        except SyntaxError as e:
            # Возвращаем объект с информацией об ошибке
            return cls(length=len(code), **{f"is_{e.msg}": True})  # type: ignore

    def to_len_stat(self) -> Dict[str, int]:
        """Возвращает подсчитывая len"""
        result = {}

        # Проходим по всем полям модели
        for field_name, field_value in self.model_dump().items():
            if isinstance(field_value, list):
                result[field_name] = len(field_value)
                continue

            result[field_name] = field_value

        return result


class CADQueryStatistics(BaseModel):
    """Статистика CadQuery операций"""

    Workplane: Optional[int] = Field(
        default=None, description="Создание рабочей плоскости"
    )
    Vector: Optional[int] = Field(default=None, description="Создание векторов")
    Plane: Optional[int] = Field(default=None, description="Создание плоскостей")

    polyline: Optional[int] = Field(default=None, description="Создание ломаной линии")
    cut: Optional[int] = Field(default=None, description="Вырезание из объекта")
    cutThruAll: Optional[int] = Field(default=None, description="Вырезание насквозь")
    cutBlind: Optional[int] = Field(default=None, description="Вырезание насквозь")
    extrude: Optional[int] = Field(default=None, description="Выдавливание")
    circle: Optional[int] = Field(default=None, description="Создание окружности")
    close: Optional[int] = Field(default=None, description="Замыкание пути (линии)")
    cylinder: Optional[int] = Field(default=None, description="Создание цилиндра")
    box: Optional[int] = Field(default=None, description="Создание коробки")
    polygon: Optional[int] = Field(default=None, description="Создание многоугольника")
    sphere: Optional[int] = Field(default=None, description="Создание сферы")
    fillet: Optional[int] = Field(default=None, description="Скругление кромок")
    chamfer: Optional[int] = Field(default=None, description="Фаска кромок")
    revolve: Optional[int] = Field(default=None, description="Операция вращения")
    loft: Optional[int] = Field(default=None, description="Операция loft")
    sweep: Optional[int] = Field(default=None, description="Операция sweep")
    union: Optional[int] = Field(default=None, description="Объединение тел")
    move: Optional[int] = Field(default=None, description="Перемещение")
    moveTo: Optional[int] = Field(default=None, description="Перемещение")
    pushPoints: Optional[int] = Field(default=None, description="Перемещение")
    translate: Optional[int] = Field(default=None, description="Трансляция")
    transformed: Optional[int] = Field(default=None, description="Трансляция")
    rotate: Optional[int] = Field(default=None, description="Вращение")
    scale: Optional[int] = Field(default=None, description="Масштабирование")
    workplane: Optional[int] = Field(
        default=None, description="Создание новой рабочей плоскости"
    )
    slot2D: Optional[int] = Field(default=None, description="Создание 2D слота")
    hole: Optional[int] = Field(default=None, description="Создание отверстия")
    rect: Optional[int] = Field(default=None, description="Создание прямоугольника")
    threePointArc: Optional[int] = Field(default=None, description="Создане арки")
    line: Optional[int] = Field(default=None, description="Построение линии")
    lineTo: Optional[int] = Field(default=None, description="Построение линии")
    spline: Optional[int] = Field(default=None, description="Построение гладкой кривой")
    parametricCurve: Optional[int] = Field(
        default=None, description="Построение параметрической кривой"
    )

    class Config:
        extra = "allow"

    @staticmethod
    def operation_constraint(
        code: str, include: list[str] | None = None, exclude: list[str] | None = None
    ):
        model = CADQueryStatistics.from_text(code)

        return (
            any(field in include and value > 0 for field, value in model)
            if include
            else True
        ) and (
            all(field in exclude and value > 0 for field, value in model)
            if exclude
            else True
        )

    @classmethod
    def from_text(cls, code: str):
        """Создает статистику CadQuery из текста кода"""
        ops = {}
        match = re.search(r"Workplane\(['\"](.*?)['\"]", code)
        if match:
            axis = match.group(1)
            ops[f"is_{axis}_orientation"] = True

        try:
            tree = ast.parse(code)

            # Создаем экземпляр с нулевыми значениями
            ops.update(
                dict.fromkeys(
                    [k for k in cls.model_fields.keys() if not k.startswith("is_")], 0
                )
            )

            # Обновляем счетчики операций
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    attr_name = node.func.attr
                    if attr_name in ops:
                        ops[attr_name] += 1

            return cls(**ops)

        except SyntaxError as e:
            # Возвращаем объект с информацией об ошибке
            return cls(**{f"is_{e.msg}": True})
