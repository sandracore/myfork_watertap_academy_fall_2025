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



# IMPORTS FROM IDAES
from idaes.core import FlowsheetBlock, UnitModelCostingBlock
from idaes.models.unit_models import Feed, Product
from idaes.core.util.model_statistics import degrees_of_freedom
from idaes.core.util.scaling import calculate_scaling_factors, set_scaling_factor
from idaes.core.util.initialization import propagate_state



# IMPORTS FROM WaterTAP
from watertap.property_models.NaCl_prop_pack import NaClParameterBlock
from watertap.property_models.seawater_prop_pack import SeawaterParameterBlock
from watertap.unit_models.pressure_changer import Pump
from watertap.unit_models.reverse_osmosis_0D import (
    ReverseOsmosis0D,
    ConcentrationPolarizationType,
    MassTransferCoefficient,
    PressureChangeType,
)

from watertap.unit_models.zero_order import ChemicalAdditionZO
from watertap.unit_models.zero_order import UltraFiltrationZO
from watertap.unit_models.zero_order import ChlorinationZO
from watertap.unit_models.zero_order import DeepWellInjectionZO

from watertap.core.wt_database import Database                                                              # What is this line for?
from watertap.core.zero_order_properties import WaterParameterBlock as ZOProperties
from watertap.costing.zero_order_costing import ZeroOrderCosting
from watertap.costing import WaterTAPCosting
from watertap.core.solvers import get_solver


# TRANSLATOR FUNCTION

import idaes.logger as idaeslog
from idaes.core import declare_process_block_class
from idaes.core.util.exceptions import InitializationError
from idaes.models.unit_models.translator import TranslatorData


@declare_process_block_class("TranslatorZOtoSW")
class TranslatorZOtoSWData(TranslatorData):
    """
    Translator block for converting from ZO TDS to SW TDS
    """

    CONFIG = TranslatorData.CONFIG()

    def build(self):
        super().build()

        @self.Constraint(
            self.flowsheet().time,
            doc="Equality mass flow water equation",
        )
        def eq_flow_mass_rule(blk, t):
            return (
                blk.properties_out[t].flow_mass_phase_comp["Liq", "H2O"]
                == blk.properties_in[t].flow_mass_comp["H2O"]
            )

        @self.Constraint(
            self.flowsheet().time,
            doc="Equality solute equation",
        )
        def eq_solute_mass_flow(blk, t):
            return (
                blk.properties_out[t].flow_mass_phase_comp["Liq", "NaCl"]
                == blk.properties_in[t].flow_mass_comp["NaCl"]
            )

        # ZO prop pack doesn't have temperature and pressure as state variables
        self.properties_out[0].pressure.fix(101325)
        self.properties_out[0].temperature.fix(298.15)

    def initialize_build(
        self,
        state_args_in=None,
        state_args_out=None,
        outlvl=idaeslog.NOTSET,
        solver=None,
        optarg=None,
    ):
        init_log = idaeslog.getInitLogger(self.name, outlvl, tag="unit")

        # Create solver
        opt = get_solver(solver, optarg)

        # ---------------------------------------------------------------------
        # Initialize state block
        flags = self.properties_in.initialize(
            outlvl=outlvl,
            optarg=optarg,
            solver=solver,
            state_args=state_args_in,
            hold_state=True,
        )

        self.properties_out.initialize(
            outlvl=outlvl,
            optarg=optarg,
            solver=solver,
            state_args=state_args_out,
        )

        if degrees_of_freedom(self) != 0:
            raise Exception(
                f"{self.name} degrees of freedom were not 0 at the beginning "
                f"of initialization. DoF = {degrees_of_freedom(self)}"
            )

        with idaeslog.solver_log(init_log, idaeslog.DEBUG) as slc:
            res = opt.solve(self, tee=slc.tee)

        self.properties_in.release_state(flags=flags, outlvl=outlvl)

        init_log.info(f"Initialization Complete: {idaeslog.condition(res)}")

        if not check_optimal_termination(res):
            raise InitializationError(
                f"{self.name} failed to initialize successfully. Please check "
                f"the output logs for more information."
            )

solute_list = ["NaCl"]

mass_flow_water = 0.965
mass_flow_salt = 0.035

use_default_removal = True

# Chemical dosing parameters
anti_scalant_dose = 1 * pyunits.mg / pyunits.liter

# Pump parameters
pump_efficiency = 0.85 * pyunits.dimensionless
operating_pressure = 75 * pyunits.bar

# RO parameters
A_comp = 4.2e-12
B_comp = 3e-8
membrane_area = 50  # m2
atmospheric = 101325  # Pa
deltaP = -3 * pyunits.bar
channel_height = 1 * pyunits.mm
spacer_porosity = 0.75
RR = 0.45

solver = get_solver()



# CREATING FUNCTIONS


def main():
    m = build()
    scale_system(m)
    add_costing(m)
    initialize_system(m)
    results = solve_system(m)
    display_costing(m)

    return m, results



def build():

    m = ConcreteModel()
    m.db = Database()                                                                                     # What is this line for?
    m.fs = FlowsheetBlock(dynamic=False)


    # Add property models
    m.fs.zo_properties = ZOProperties(solute_list=solute_list)
    m.fs.ro_properties = NaClParameterBlock()
    #m.fs.ro_properties = SeawaterParameterBlock()

    # Add unit models
    m.fs.feed = Feed(property_package=m.fs.zo_properties)
    # Set feed stream
    m.fs.feed.properties[0].flow_mass_comp["H2O"].fix(mass_flow_water)
    m.fs.feed.properties[0].flow_mass_comp["NaCl"].fix(mass_flow_salt)
    #m.fs.feed.properties[0].flow_mass_comp["TDS"].fix(mass_flow_salt)


    m.fs.ultra_filt = UltraFiltrationZO(property_package=m.fs.zo_properties, database=m.db)                                             # Where to see arguments required for each function
    m.fs.chem_addition = ChemicalAdditionZO(property_package=m.fs.zo_properties,database=m.db,process_subtype="anti-scalant")           # Where to see arguments required for each function
    m.fs.chem_addition.chemical_dosage.fix(anti_scalant_dose)
    m.fs.translator_feed = TranslatorZOtoSW(inlet_property_package=m.fs.zo_properties,outlet_property_package=m.fs.ro_properties)       # How to fix this translation to NaCl instead of SW
    #m.fs.translator_brine = TranslatorZOtoSW(inlet_property_package=m.fs.zo_properties,outlet_property_package=m.fs.ro_properties)




    m.fs.pump = Pump(property_package=m.fs.ro_properties)
    m.fs.pump.efficiency_pump.fix(pump_efficiency)
    m.fs.pump.control_volume.properties_out[0].pressure.fix(operating_pressure)


    m.fs.RO = ReverseOsmosis0D(
        property_package=m.fs.ro_properties,
        has_pressure_change=True,
        pressure_change_type=PressureChangeType.calculated,
        mass_transfer_coefficient=MassTransferCoefficient.calculated,
        concentration_polarization_type=ConcentrationPolarizationType.calculated,
        module_type="spiral_wound",
    )

    # Fix (2) membrane properties
    m.fs.RO.A_comp.fix(A_comp)
    m.fs.RO.B_comp.fix(B_comp)

    # Fix (4) module specifications
    m.fs.RO.feed_side.channel_height.fix(channel_height)
    m.fs.RO.feed_side.spacer_porosity.fix(spacer_porosity)
    m.fs.RO.area.fix(membrane_area)
    m.fs.RO.deltaP.fix(deltaP)
    #m.fs.RO.recovery_vol_phase[0.0, "Liq"].fix(RR)

    # (1) outlet state variable
    m.fs.RO.permeate.pressure[0].fix(atmospheric)



    # Create an Expression to calculate flux in LMH
    m.fs.RO.flux_LMH = Expression(
        expr=pyunits.convert(
            m.fs.RO.mixed_permeate[0].flow_vol_phase["Liq"] / m.fs.RO.area,
            to_units=pyunits.liter / (pyunits.m**2 * pyunits.hr),
        )
    )

    m.fs.product = Product(property_package=m.fs.ro_properties)
    m.fs.product.properties[0].conc_mass_phase_comp                                                         # What is this line doing?

    #m.fs.brine = Product(property_package=m.fs.ro_properties)
    #m.fs.brine.properties[0].conc_mass_phase_comp                                                           # What is this line doing?

    #m.fs.chlorination = ChlorinationZO(property_package=m.fs.zo_properties, database=m.db)                                             # Where to see arguments required for each function
    #m.fs.dwi = DeepWellInjectionZO(property_package=m.fs.zo_properties,database=m.db)                                                  # Where to see arguments required for each function


    # Connect unit models with Arcs

    m.fs.feed_to_ultra = Arc(source=m.fs.feed.outlet, destination=m.fs.ultra_filt.inlet)
    m.fs.ultra_to_chem = Arc(source=m.fs.ultra_filt.treated, destination=m.fs.chem_addition.inlet)
    m.fs.chem_to_trans = Arc(source=m.fs.chem_addition.outlet, destination=m.fs.translator_feed.inlet)
    m.fs.trans_to_pump = Arc(source=m.fs.translator_feed.outlet, destination=m.fs.pump.inlet)
    m.fs.pump_to_RO = Arc(source=m.fs.pump.outlet, destination=m.fs.RO.inlet)
    m.fs.RO_to_product = Arc(source=m.fs.RO.permeate, destination=m.fs.product.inlet)                       # How to add chlorination and remineralization after this?

    TransformationFactory("network.expand_arcs").apply_to(m)  

    return m

def scale_system(m):
    # Set scaling factors
    m.fs.ro_properties.set_default_scaling("flow_mass_phase_comp", 1, index=("Liq", "H2O"))
    m.fs.ro_properties.set_default_scaling("flow_mass_phase_comp", 1e2, index=("Liq", "TDS"))

    m.fs.zo_properties.set_default_scaling("flow_mass_comp", 1, index=("H2O"))
    m.fs.zo_properties.set_default_scaling("flow_mass_comp", 1e2, index=("TDS"))

    set_scaling_factor(m.fs.pump.control_volume.work, 1e-3)
    set_scaling_factor(m.fs.RO.area, 1e-2)
    calculate_scaling_factors(m)


    # Release constraints related to low concentrations
    for item in [m.fs.RO.permeate_side, m.fs.RO.feed_side.properties_interface]:
        for idx, param in item.items():
            param.molality_phase_comp["Liq", "NaCl"].setlb(1e-5)
            param.pressure_osm_phase["Liq"].setlb(10)

    print(f"dof = {degrees_of_freedom(m)}")


def add_costing(m):

    m.fs.costing = WaterTAPCosting()                                                                       # What cost model should be used? Zero order or waterTap Costing?
    m.fs.costing = ZeroOrderCosting()
    m.fs.costing.base_currency = pyunits.USD_2023

    m.fs.ultra_filt.costing = UnitModelCostingBlock(flowsheet_costing_block=m.fs.costing)
    m.fs.chem_addition.costing = UnitModelCostingBlock(flowsheet_costing_block=m.fs.costing)
    m.fs.pump.costing = UnitModelCostingBlock(flowsheet_costing_block=m.fs.costing)
    m.fs.RO.costing = UnitModelCostingBlock(flowsheet_costing_block=m.fs.costing)

    m.fs.costing.cost_process()
    m.fs.costing.add_LCOW(m.fs.product.properties[0].flow_vol_phase["Liq"])
    m.fs.costing.add_specific_energy_consumption(m.fs.product.properties[0].flow_vol_phase["Liq"], name="SEC")

def initialize_system(m):

    solver = get_solver()
    
    propagate_state(m.fs.feed_to_ultra)
    m.fs.ultra_filt.load_parameters_from_database(use_default_removal=use_default_removal)              # What do I need this line?
    m.fs.ultra_filt.initialize()

    print(f"dof = {degrees_of_freedom(m)}")

    propagate_state(m.fs.ultra_to_chem)
    m.fs.chem_addition.load_parameters_from_database(use_default_removal=use_default_removal)
    m.fs.chem_addition.initialize()

    propagate_state(m.fs.chem_to_trans)
    m.fs.translator_feed.initialize()

    propagate_state(m.fs.trans_to_pump)
    m.fs.pump.initialize()

    propagate_state(m.fs.pump_to_RO)
    m.fs.RO.initialize()

    propagate_state(m.fs.RO_to_product)
    m.fs.product.initialize()



def solve_system(m):
    print(f"dof = {degrees_of_freedom(m)}")
    assert degrees_of_freedom(m) == 0
    solver = get_solver()
    results = solver.solve(m)
    assert_optimal_termination(results)

    return results


def display_costing(m):
    m.fs.costing.LCOW.display()
    m.fs.costing.SEC.display()
    m.fs.costing.aggregate_flow_costs.display()
    m.fs.costing.aggregate_flow_electricity.display()
    m.fs.costing.SEC_component.display()

    m.fs.costing.total_capital_cost.display()
    m.fs.costing.total_operating_cost.display()
    m.fs.pump.work_mechanical.display()
    m.fs.RO.recovery_vol_phase.display()
    m.fs.product.properties[0].conc_mass_phase_comp.display()
    m.fs.brine.properties[0].conc_mass_phase_comp.display()


if __name__ == "__main__":
    m, results = main()


