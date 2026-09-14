#include "stm32f4xx_hal.h"
UART_HandleTypeDef huart2;
SPI_HandleTypeDef hspi1;
static void MX_USART2_UART_Init(void);
static void MX_SPI1_Init(void);
static void MX_GPIO_Init(void);
void SystemClock_Config(void);

int main(void) {
  uint8_t msg[] = "ready\r\n";
  uint8_t buf[4] = {0};
  HAL_Init();
  SystemClock_Config();
  MX_GPIO_Init();
  MX_USART2_UART_Init();
  HAL_UART_Transmit(&huart2, msg, sizeof(msg) - 1, HAL_MAX_DELAY);
  HAL_SPI_Transmit(&hspi1, buf, sizeof(buf), 100);
  while (1) { HAL_Delay(500); }
}

static void MX_USART2_UART_Init(void) {
  huart2.Instance = USART2;
  huart2.Init.BaudRate = 115200;
  huart2.Init.WordLength = UART_WORDLENGTH_8B;
  huart2.Init.StopBits = UART_STOPBITS_1;
  huart2.Init.Parity = UART_PARITY_NONE;
  huart2.Init.Mode = UART_MODE_TX_RX;
  huart2.Init.OverSampling = UART_OVERSAMPLING_16;
  if (HAL_UART_Init(&huart2) != HAL_OK) { Error_Handler(); }
}

static void MX_SPI1_Init(void) {
  hspi1.Instance = SPI1;
  hspi1.Init.Mode = SPI_MODE_MASTER;
  hspi1.Init.BaudRatePrescaler = SPI_BAUDRATEPRESCALER_16;
  if (HAL_SPI_Init(&hspi1) != HAL_OK) { Error_Handler(); }
}

static void MX_GPIO_Init(void) { __HAL_RCC_GPIOA_CLK_ENABLE(); }
void HAL_UART_MspInit(UART_HandleTypeDef* uartHandle) { /* pin setup */ }
