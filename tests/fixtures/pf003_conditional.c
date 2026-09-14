#include "stm32f4xx_hal.h"
UART_HandleTypeDef huart2;

int main(void) {
  uint8_t msg[] = "hi\r\n";
  HAL_Init();
#if 0
  HAL_UART_Init(&huart2);
#endif
  HAL_UART_Transmit(&huart2, msg, sizeof(msg) - 1, HAL_MAX_DELAY);
  while (1) { }
}
