from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any, Callable, ClassVar, Dict, List, Optional

import numpy as np
from pydantic import BaseModel, Field, computed_field

if TYPE_CHECKING:
    import trimesh


class MeshStatistics(BaseModel):
    invalid_checks: ClassVar[dict[str, Callable[[trimesh.Trimesh], Optional[bool]]]] = {
        "is_empty": lambda mesh: mesh.is_empty,
        "is_zero_volume": lambda mesh: not bool(mesh.volume > 0),
        "is_0d": lambda mesh: (
            bool(sum(mesh.extents == 0) == 3) if mesh.extents is not None else None
        ),
        "is_1d": lambda mesh: (
            bool(sum(mesh.extents == 0) == 2) if mesh.extents is not None else None
        ),
        "is_2d": lambda mesh: (
            bool(sum(mesh.extents == 0) == 1) if mesh.extents is not None else None
        ),
        "is_not_watertight": lambda mesh: not mesh.is_watertight,
    }

    class Config:
        arbitrary_types_allowed = True

    if TYPE_CHECKING:
        mesh: Optional[trimesh.Trimesh] = Field(default=None, exclude=True)
    else:
        mesh: Optional[Any] = Field(default=None, exclude=True)

    # Базовые топологические свойства
    vertices_count: Optional[int] = Field(
        default=None, description="Количество вершин в меше"
    )
    faces_count: Optional[int] = Field(
        default=None, description="Количество граней в меше"
    )
    edges_count: Optional[int] = Field(
        default=None, description="Количество ребер в меше"
    )
    edges_unique_count: Optional[int] = Field(
        default=None, description="Количество уникальных ребер"
    )
    euler_number: Optional[int] = Field(
        default=None, description="Число Эйлера (топологическая характеристика)"
    )

    # Геометрические характеристики
    volume: Optional[float] = Field(default=None, description="Объем меша")
    area: Optional[float] = Field(default=None, description="Площадь поверхности меша")
    density: Optional[float] = Field(
        default=None, description="Плотность (объем/площадь)"
    )

    # Размеры и bounding box
    bounds_min: Optional[List[float]] = Field(
        default=None, description="Минимальные координаты bounding box"
    )
    bounds_max: Optional[List[float]] = Field(
        default=None, description="Максимальные координаты bounding box"
    )
    extent_x: Optional[float] = Field(default=None, description="Размер по оси X")
    extent_y: Optional[float] = Field(default=None, description="Размер по оси Y")
    extent_z: Optional[float] = Field(default=None, description="Размер по оси Z")
    bounding_box_volume: Optional[float] = Field(
        default=None, description="Объем bounding box"
    )

    # Центры
    center_mass: Optional[List[float]] = Field(default=None, description="Центр масс")
    centroid: Optional[List[float]] = Field(default=None, description="Центроид")

    # Топологические свойства
    is_not_watertight: Optional[bool] = Field(
        default=None, description="Является ли меш водонепроницаемым"
    )
    is_convex: Optional[bool] = Field(
        default=None, description="Является ли меш выпуклым"
    )
    is_empty: Optional[bool] = Field(default=None, description="Является ли меш пустым")

    # Качество меша
    face_area_mean: Optional[float] = Field(
        default=None, description="Средняя площадь грани"
    )
    face_area_std: Optional[float] = Field(
        default=None, description="Стандартное отклонение площадей граней"
    )
    face_area_min: Optional[float] = Field(
        default=None, description="Минимальная площадь грани"
    )
    face_area_max: Optional[float] = Field(
        default=None, description="Максимальная площадь грани"
    )

    # Соотношения и метрики качества
    sphericity: Optional[float] = Field(
        default=None, description="Сферичность (0-1), None если volume <= 0"
    )
    volume_fill_ratio: Optional[float] = Field(
        default=None,
        description="Коэффициент заполнения bounding box, None если bounding_box_volume <= 0",
    )

    # Нормали
    average_face_normal: Optional[List[float]] = Field(
        default=None, description="Средняя нормаль граней"
    )

    # Компоненты связности
    connected_components: Optional[int] = Field(
        default=None, description="Количество компонент связности"
    )
    components_watertight: Optional[int] = Field(
        default=None, description="Количество водонепроницаемых компонент"
    )

    # Ошибки
    error: Optional[str] = Field(
        default=None, description="Ошибка при вычислении статистики"
    )

    @computed_field()
    def is_zero_volume(self) -> bool | None:
        if self.mesh is None:
            return None
        return not bool(self.mesh.volume > 0)

    @computed_field()
    def is_0d(self) -> bool | None:
        if self.mesh is None or self.mesh.extents is None:
            return None
        return bool(sum(self.mesh.extents == 0) == 3)

    @computed_field()
    def is_1d(self) -> bool | None:
        if self.mesh is None or self.mesh.extents is None:
            return None
        return bool(sum(self.mesh.extents == 0) == 2)

    @computed_field()
    def is_2d(self) -> bool | None:
        if self.mesh is None or self.mesh.extents is None:
            return None
        return bool(sum(self.mesh.extents == 0) == 1)

    @computed_field()
    def is_3d(self) -> bool | None:
        if self.mesh is None or self.mesh.extents is None:
            return None
        return bool(sum(self.mesh.extents == 0) == 0)

    @classmethod
    def from_mesh(cls, mesh: trimesh.Trimesh) -> "MeshStatistics":
        """Создает объект статистики из меша trimesh"""
        stats_data: Dict[str, Any] = {}

        try:
            # Топологические свойства
            stats_data["is_empty"] = bool(mesh.is_empty)
            if not bool(mesh.is_empty):

                stats_data["is_not_watertight"] = not bool(mesh.is_watertight)
                stats_data["is_convex"] = bool(mesh.is_convex)
                # Базовые топологические свойства
                stats_data["vertices_count"] = len(mesh.vertices)
                stats_data["faces_count"] = len(mesh.faces)
                stats_data["edges_count"] = len(mesh.edges)
                stats_data["edges_unique_count"] = len(mesh.edges_unique)
                stats_data["euler_number"] = int(mesh.euler_number)

                # Геометрические характеристики
                stats_data["volume"] = float(mesh.volume)
                stats_data["area"] = float(mesh.area)
                stats_data["density"] = (
                    float(mesh.volume / mesh.area) if mesh.area > 0 else 0.0
                )

                # Размеры и bounding box
                bounds = mesh.bounds
                stats_data["bounds_min"] = bounds[0].tolist()
                stats_data["bounds_max"] = bounds[1].tolist()

                extents = mesh.extents
                stats_data["extent_x"] = float(extents[0])
                stats_data["extent_y"] = float(extents[1])
                stats_data["extent_z"] = float(extents[2])
                stats_data["bounding_box_volume"] = float(
                    extents[0] * extents[1] * extents[2]
                )

                # Центры
                stats_data["center_mass"] = mesh.center_mass.tolist()
                stats_data["centroid"] = mesh.centroid.tolist()

                # Качество меша
                areas = mesh.area_faces
                stats_data["face_area_mean"] = float(areas.mean())
                stats_data["face_area_std"] = float(areas.std())
                stats_data["face_area_min"] = float(areas.min())
                stats_data["face_area_max"] = float(areas.max())

                # Соотношения и метрики качества
                if mesh.volume > 0:
                    stats_data["sphericity"] = float(
                        (math.pi ** (1 / 3)) * (6 * mesh.volume) ** (2 / 3) / mesh.area
                    )

                if stats_data["bounding_box_volume"] > 0:
                    stats_data["volume_fill_ratio"] = float(
                        mesh.volume / stats_data["bounding_box_volume"]
                    )

                # Нормали
                if hasattr(mesh, "face_normals") and mesh.face_normals is not None:
                    stats_data["average_face_normal"] = mesh.face_normals.mean(
                        axis=0
                    ).tolist()

                # ! to slow
                # Компоненты связности
                # stats_data["connected_components"] = 1
                # stats_data["components_watertight"] = 1 if mesh.is_watertight else 0

                # if hasattr(mesh, "faces") and len(mesh.faces) > 0:
                #     try:
                #         components = mesh.split(only_watertight=False)
                #         stats_data["connected_components"] = len(components)
                #         stats_data["components_watertight"] = sum(
                #             1 for comp in components if comp.is_watertight
                #         )
                #     except Exception:
                #         pass

                stats_data["mesh"] = mesh

        except Exception as ex:
            print(ex)
            stats_data["error"] = str(ex)

        return cls(**stats_data)

    @staticmethod
    def check_invalid(
        mesh_or_dict: trimesh.Trimesh | dict[str, Any],
    ) -> tuple[bool, dict[str, bool | None]]:
        if isinstance(mesh_or_dict, dict):
            result = {
                key: mesh_or_dict.get(key)
                for key in MeshStatistics.invalid_checks.keys()
            }

        else:
            result = {
                key: check(mesh_or_dict)
                for key, check in MeshStatistics.invalid_checks.items()
            }

        return any(result.values()), result


def euler_check(x: trimesh.Trimesh, y):

    return (
        x.euler_number <= 20
        and x.euler_number >= -20
        and x.volume >= 100
        and len(x.vertices) <= 5000
    )


def check_normals_consistency(mesh):
    """Проверяет согласованность нормалей"""
    try:
        # Если меш имеет face normals, проверяем их согласованность
        if hasattr(mesh, "face_normals"):
            dot_products = np.dot(mesh.face_normals, mesh.face_normals.mean(axis=0))
            return (
                np.mean(dot_products) > 0.7
            )  # Большинство нормалей смотрят в одном направлении
        return True
    except Exception:
        return False


def check_printable_orientation(mesh):
    """Проверяет, можно ли напечатать модель без поддержек"""
    try:
        # Простая проверка: основная плоскость должна быть снизу
        bounds = mesh.bounds
        # height = bounds[1][2] - bounds[0][2]
        base_area = (bounds[1][0] - bounds[0][0]) * (bounds[1][1] - bounds[0][1])
        return base_area > mesh.area * 0.3  # Достаточно плоское основание
    except Exception:
        return False


def check_overhangs(mesh, max_angle=45.0):
    """Проверяет наличие критических свесов"""
    try:
        if hasattr(mesh, "face_normals"):
            # Угол между нормалью грани и вертикалью (Z-axis)
            vertical = np.array([0, 0, 1])
            angles = np.degrees(
                np.arccos(np.clip(np.dot(mesh.face_normals, vertical), -1.0, 1.0))
            )
            # Минимальный угол среди всех граней (самый крутой свес)
            min_angle = np.min(angles)
            return min_angle <= max_angle
        return True
    except Exception:
        return False
