from aiocryptopay import AioCryptoPay, Networks
import config
import logging

# 1. Создаем пустую переменную (пока не подключаемся)
_client = None


# 2. Функция для получения клиента (подключается только когда нужно)
def get_crypto_client():
    global _client
    if _client is None:
        # Вот теперь, когда бот уже запущен, мы создаем подключение безопасно
        _client = AioCryptoPay(token=config.CRYPTO_BOT_TOKEN, network=Networks.MAIN_NET)
    return _client


async def create_crypto_invoice(amount, description, payload):
    try:
        # Получаем клиента через функцию
        client = get_crypto_client()

        invoice = await client.create_invoice(
            asset='USDT',
            amount=str(amount),
            description=description,
            payload=payload,
            expires_in=3600
        )
        return invoice
    except Exception as e:
        logging.error(f"❌ ОШИБКА CRYPTOBOT: {e}")
        return None


async def check_crypto_status(invoice_id):
    try:
        # Получаем клиента через функцию
        client = get_crypto_client()

        invoices = await client.get_invoices(invoice_ids=[invoice_id])
        if invoices:
            return invoices[0].status
    except Exception as e:
        logging.error(f"Ошибка проверки Crypto: {e}")
    return None


async def close():
    global _client
    if _client:
        await _client.close()