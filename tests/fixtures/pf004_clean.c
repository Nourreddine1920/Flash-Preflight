#include "stm32f4xx_hal.h"
void MX_NVIC_Init(void) {
  HAL_NVIC_SetPriorityGrouping(NVIC_PRIORITYGROUP_4);
  HAL_NVIC_SetPriority(USART2_IRQn, 5, 0);
  HAL_NVIC_EnableIRQ(USART2_IRQn);
  HAL_NVIC_SetPriority(TIM2_IRQn, 6, 0);
  HAL_NVIC_EnableIRQ(TIM2_IRQn);
}
