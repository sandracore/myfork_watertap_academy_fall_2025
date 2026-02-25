# IMPORTS FROM PYOMO
from pyomo.environ import (
    ConcreteModel,
    Var,
    Param,
    Constraint,
    Objective,
    Expression,
    value,
    check_optimal_termination,
    assert_optimal_termination,
    TransformationFactory,
    units as pyunits,
)


from pyomo.network import Arc
from pyomo.util.check_units import assert_units_consistent


# IMPORTS FROM IDAES
from idaes.core import FlowsheetBlock
from idaes.core.util.initialization import (
    propagate_state,
    fix_state_vars,
    revert_state_vars,
)
from idaes.core.util.exceptions import ConfigurationError
from idaes.models.unit_models.translator import Translator
from idaes.models.unit_models import Mixer, Separator
from idaes.models.unit_models.mixer import MomentumMixingType
import idaes.core.util.scaling as iscale
import idaes.logger as idaeslog
from idaes.core import UnitModelCostingBlock
from idaes.models.unit_models import Feed, Product
from idaes.core.util.model_statistics import degrees_of_freedom
from idaes.core.util.scaling import calculate_scaling_factors, set_scaling_factor


# IMPORTS FROM WaterTAP
from watertap.core.solvers import get_solver
import watertap.property_models.seawater_prop_pack as prop_SW
from watertap.unit_models.reverse_osmosis_0D import (
    ReverseOsmosis0D,
    ConcentrationPolarizationType,
    MassTransferCoefficient,
    PressureChangeType,
)
from watertap.property_models.NaCl_prop_pack import NaClParameterBlock
from watertap.property_models.seawater_prop_pack import SeawaterParameterBlock
from watertap.unit_models.pressure_exchanger import PressureExchanger
from watertap.unit_models.pressure_changer import Pump, EnergyRecoveryDevice
from watertap.core.util.initialization import assert_degrees_of_freedom, check_solve

from watertap.core.wt_database import Database
import watertap.core.zero_order_properties as prop_ZO
from watertap.unit_models.zero_order import (
    FeedZO,
    SWOnshoreIntakeZO,
    ChemicalAdditionZO,
    ChlorinationZO,
    StaticMixerZO,
    StorageTankZO,
    MediaFiltrationZO,
    BackwashSolidsHandlingZO,
    CartridgeFiltrationZO,
    UVAOPZO,
    CO2AdditionZO,
    MunicipalDrinkingZO,
    LandfillZO,
    UltraFiltrationZO,
)
from watertap.costing.zero_order_costing import ZeroOrderCosting
from watertap.core.zero_order_properties import WaterParameterBlock as ZOProperties
from watertap.costing import WaterTAPCosting


# TRANSLATOR FUNCTION

import idaes.logger as idaeslog
from idaes.core import declare_process_block_class
from idaes.core.util.exceptions import InitializationError
from idaes.models.unit_models.translator import TranslatorData


# Set up logger
_log = idaeslog.getLogger(__name__)
