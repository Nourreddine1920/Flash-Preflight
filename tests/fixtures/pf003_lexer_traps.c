#include "stm32f4xx_hal.h"
SPI_HandleTypeDef hspi1;
UART_HandleTypeDef huart2;
/* HAL_SPI_Transmit(&hspi1, 0, 0, 0);  <- in a block comment, must be ignored */
static const char *help = "call HAL_SPI_Transmit(&hspi1, buf, 4, 100) to send";
int main(void) {
  // HAL_UART_Transmit(&huart2, 0, 0, 0);   <- line comment, must be ignored
  const char *tricky = "/* not a comment */ HAL_UART_Transmit(&huart2,0,0,0)";
  (void)help; (void)tricky;
  while (1) { }
}
