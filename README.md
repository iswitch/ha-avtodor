# Автодор

Баланс лицевых счетов «Автодор — Платные Дороги» в Home Assistant.

<!-- ha-marketplace:exclude-start -->

## Установка через Marketplace

В Home Assistant 2026.11 или новее откройте «Настройки → Marketplace», найдите «Автодор» и нажмите «Установить». Если Marketplace запросит перезапуск Home Assistant, выполните его.

[![Открыть в Marketplace](https://my.home-assistant.io/badges/marketplace_repository.svg)](https://my.home-assistant.io/redirect/marketplace_repository/?owner=iswitch&repository=ha-avtodor&category=integration)

В Home Assistant 2026.10 интеграцию можно установить через [HACS](https://my.home-assistant.io/redirect/hacs_repository/?owner=iswitch&repository=ha-avtodor&category=integration).

## Ручная установка

Скопируйте `custom_components/avtodor` в каталог `custom_components` Home Assistant и перезапустите сервер.

<!-- ha-marketplace:exclude-end -->

## Настройка

В разделе «Настройки → Устройства и службы → Добавить интеграцию» выберите «Автодор» и введите логин и пароль личного кабинета.

Баланс обновляется каждые 5 минут. Интервал меняется в параметрах интеграции. Для каждого лицевого счёта создаются сенсоры баланса и бонусных баллов. Для транспондеров доступны статус и интероперабельность, для каждого автомобиля — госномер, задолженность и количество нарушений отдельными сенсорами. Новые транспондеры и госномера обнаруживаются автоматически. При ошибке связи сенсор становится недоступен, при ошибке входа запрашивается повторная авторизация.

Требуется Home Assistant 2026.10 или новее. Используется API мобильного приложения с автоматическим обновлением токена; интеграция не является официальным продуктом Автодора. Знак Автодора принадлежит правообладателю.
