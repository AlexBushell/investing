from __future__ import annotations

from app.business_models.base import BusinessModel
from app.business_models.cloud_software_ai_infrastructure import CloudSoftwareAiInfrastructureModel
from app.business_models.generic_revenue_margin_fcf import GenericRevenueMarginFcfModel
from app.business_models.housebuilder import HousebuilderModel
from app.business_models.low_cost_gym_ifrs16 import LowCostGymIfrs16Model


_REGISTRY: dict[str, BusinessModel] = {
    CloudSoftwareAiInfrastructureModel.business_model_type: CloudSoftwareAiInfrastructureModel(),
    GenericRevenueMarginFcfModel.business_model_type: GenericRevenueMarginFcfModel(),
    HousebuilderModel.business_model_type: HousebuilderModel(),
    LowCostGymIfrs16Model.business_model_type: LowCostGymIfrs16Model(),
}


def get_business_model(model_type: str) -> BusinessModel:
    try:
        return _REGISTRY[model_type]
    except KeyError as exc:
        raise ValueError(f"Unsupported business_model_type: {model_type}") from exc


def list_business_models() -> list[str]:
    return sorted(_REGISTRY)
