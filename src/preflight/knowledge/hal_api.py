"""Which HAL functions count as "init" vs "use" for PF003, per peripheral kind.

Explicit tables, not pattern inference: a naive `HAL_\\w+_Init` regex would
also match `HAL_UART_MspInit`, which is a callback invoked by `HAL_UART_Init`
itself, not an init call a user makes -- it must never count as one.
"""

from __future__ import annotations

import re

INIT_FNS: dict[str, set[str]] = {
    "UART": {
        "HAL_UART_Init",
        "HAL_HalfDuplex_Init",
        "HAL_LIN_Init",
        "HAL_MultiProcessor_Init",
        "HAL_RS485Ex_Init",
    },
    "SPI": {"HAL_SPI_Init"},
    "I2C": {"HAL_I2C_Init"},
    "ADC": {"HAL_ADC_Init"},
    "TIM": {
        "HAL_TIM_Base_Init",
        "HAL_TIM_PWM_Init",
        "HAL_TIM_IC_Init",
        "HAL_TIM_OC_Init",
        "HAL_TIM_Encoder_Init",
        "HAL_TIM_OnePulse_Init",
    },
    "CAN": {"HAL_CAN_Init"},
    "DAC": {"HAL_DAC_Init"},
}

USE_FNS: dict[str, set[str]] = {
    "UART": {
        "HAL_UART_Transmit",
        "HAL_UART_Receive",
        "HAL_UART_Transmit_IT",
        "HAL_UART_Receive_IT",
        "HAL_UART_Transmit_DMA",
        "HAL_UART_Receive_DMA",
    },
    "SPI": {
        "HAL_SPI_Transmit",
        "HAL_SPI_Receive",
        "HAL_SPI_TransmitReceive",
        "HAL_SPI_Transmit_IT",
        "HAL_SPI_Receive_IT",
        "HAL_SPI_TransmitReceive_IT",
        "HAL_SPI_Transmit_DMA",
        "HAL_SPI_Receive_DMA",
        "HAL_SPI_TransmitReceive_DMA",
    },
    "I2C": {
        "HAL_I2C_Master_Transmit",
        "HAL_I2C_Master_Receive",
        "HAL_I2C_Mem_Write",
        "HAL_I2C_Mem_Read",
        "HAL_I2C_IsDeviceReady",
        "HAL_I2C_Master_Transmit_IT",
        "HAL_I2C_Master_Receive_IT",
        "HAL_I2C_Master_Transmit_DMA",
        "HAL_I2C_Master_Receive_DMA",
    },
    "ADC": {"HAL_ADC_Start", "HAL_ADC_Start_IT", "HAL_ADC_Start_DMA", "HAL_ADC_GetValue"},
    "TIM": {
        "HAL_TIM_Base_Start",
        "HAL_TIM_Base_Start_IT",
        "HAL_TIM_Base_Start_DMA",
        "HAL_TIM_PWM_Start",
        "HAL_TIM_PWM_Start_IT",
        "HAL_TIM_IC_Start",
        "HAL_TIM_OC_Start",
        "HAL_TIM_Encoder_Start",
    },
    "CAN": {"HAL_CAN_Start", "HAL_CAN_AddTxMessage", "HAL_CAN_GetRxMessage"},
    "DAC": {"HAL_DAC_Start", "HAL_DAC_SetValue"},
}

DEINIT_FNS: dict[str, set[str]] = {
    kind: {f"HAL_{kind}_DeInit"} for kind in ("UART", "SPI", "I2C", "ADC", "CAN", "DAC")
} | {"TIM": {"HAL_TIM_Base_DeInit", "HAL_TIM_PWM_DeInit", "HAL_TIM_IC_DeInit", "HAL_TIM_OC_DeInit"}}

# HAL_*_MspInit / MspDeInit / *Callback names match a naive `HAL_\w+_Init`
# pattern but are neither init nor use calls, ever.
NEVER_INIT_OR_USE = re.compile(r"^HAL_\w+_(Msp(De)?Init|\w*Callback)$")

ALL_INIT_FNS: set[str] = {fn for fns in INIT_FNS.values() for fn in fns}
ALL_USE_FNS: set[str] = {fn for fns in USE_FNS.values() for fn in fns}
ALL_DEINIT_FNS: set[str] = {fn for fns in DEINIT_FNS.values() for fn in fns}


def classify_call(fn_name: str) -> str | None:
    """Returns "init", "use", "deinit", or None (not a HAL init/use/deinit call)."""
    if NEVER_INIT_OR_USE.match(fn_name):
        return None
    if fn_name in ALL_INIT_FNS:
        return "init"
    if fn_name in ALL_USE_FNS:
        return "use"
    if fn_name in ALL_DEINIT_FNS:
        return "deinit"
    return None
