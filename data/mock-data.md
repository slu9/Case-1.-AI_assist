# Мок-данные для прототипа AI-интерфейса (MVP)

> Все значения enum валидны относительно `task.md` ([§2](task.md#sec-2)); JSON баннеров/контента валиден по схемам [§2.6](task.md#sec-2-6)–[§2.7](task.md#sec-2-7) `task.md`.
> Файлы: `mocks/*.json` (18 JSON-файлов).

<a id="sec-0"></a>
## 0. Соглашения

ID в моках — просто примеры, а не требование к нумерации: команды генерируют идентификаторы как удобно, схема данных от них не зависит. В примерах ниже ссылки между сущностями идут по id из моков (кампания 101, баннер 201, контент 301, креатив 401 и т.д.).

Обозначения: `«полный»` — все необязательные поля заполнены; `«минимальный»` — только обязательные (необязательные отсутствуют — так и задумано).
Пользователи: `ivanov.p` (campaignManager) — создание и правки кампаний; `petrova.m` (campaignModerator) — модерация (approve/decline). Пользователь и роль передаются в заголовках `X-User`/`X-Role` ([§3](task.md#sec-3) task.md).

Контракты чтения ([§3](task.md#sec-3) task.md): ответ `GET /campaigns` — лёгкий CampaignListItemDto (id, name, state, published, topic, даты); `campaigns.json` — данные уровня хранения, а не форма ответа. `GET /campaigns/{id}` — CampaignDetailsDto: шапка сырыми значениями (topic — string, tags/places — [id]) + вложенные `banners[]`, `contents[]`, `creatives[]`, `segments: {included, excluded}`. `lifecycle_transitions.json` — проекция журнала аудита (только переходы ЖЦ кампании, `entity=CAMPAIGN`); полный формат записи и чтение — [§3](task.md#sec-3) task.md (`GET /campaigns/{id}/audit`).

Матрица кампаний (покрыты все состояния, достижимые в MVP; ARCHIVED вне скоупа — [§6.4](task.md#sec-6-4) task.md):

| ID | Имя | STATE | Особенности |
|---|---|---|---|
| 101 | «Премиальная карта: осенняя акция» | DRAFT | Полный payload (все необязательные поля) |
| 102 | «Кэшбэк за автоплатежи» | ACTIVE | Полный цикл пройден (log в `lifecycle_transitions.json`) |
| 103 | «Сомелье: подбор вина» | ON_MODERATION | Минимальный payload; warning «нет тегов» |
| 104 | «Ипотека: ставка 4,9%» | NEEDS_WORK | Отклонена модератором; 3 warnings; нет баннеров/креативов |
| 106 | «Путешествия: кэшбэк на отели» | ACTIVE_EDITING | Активная с правкой после публикации; 3 места; warning «не все креативы» |
| 107 | «Страхование выезда за рубеж» | APPROVED | Одобрена, ждёт активации; веб-креатив |
| 108 | «Курс по финансовой грамотности» | DRAFT | Минимальный баннер без текста/кнопки; ALL_USERS; warning «не все креативы» |
| 109 | «Мобильная подписка: месяц в подарок» | ACTIVE_EDITING | Warnings пустые; правка после публикации |
| 110 | «Автокредит: ставка от 7,9%» | ON_MODERATION | Два места, креатив только для одного |
| 111 | «Зимний марафон скидок» | DRAFT | Конец в январе 2027; EVENT; креатив Web без контента |
| 112 | «Онбординг в инвестиции» | DRAFT | Исключение-продукт; 2 места одного типа |
| 113 | «Летний кешбэк: архив» | DRAFT | Единственное место неактивно (place 8) |
| 114 | «Дебетовая карта: бесплатные переводы» | STOPPED | Остановлена из ACTIVE вручную |
| 115 | «Подписка на фильмы: первый месяц 1₽» | NEEDS_WORK | Отклонена по контенту; кнопка closeCampaign |

Флаг `published` (идёт в паре со `state`, [§2.3](task.md#sec-2-3) task.md): `true` у 102, 106, 109 — показ идёт; у остальных `false`. У 114 — `false`: стоп снимает флаг.

---

<a id="sec-1"></a>
## 1. Справочники

<a id="sec-1-1"></a>
### 1.1 Темы и теги

TOPIC (topics.json) — 11 значений: `EXTRA, EVENT, RECOMMENDATION, SALES, FINANCIAL_TIPS, LIFESTYLE, RETARGET, ADVICES, HINTS, COURSES, OTHER` (в файле — {value, label}); фиксированный enum, создание новых значений не предусмотрено.
TAG (tags.json) — 6 тегов: Банковские продукты(1), Промо(2), Скидки(3), Карты(4), Вклад(5), Онбординг(6). Создание: `POST /tags` — обязательно только `name`, `id` генерирует бэкенд.

<a id="sec-1-2"></a>
### 1.2 Каналы и типы баннеров

CHANNEL (channels.json): `iOS`(1), `ANDROID`(2), `WEB`(3).

BANNER_TYPE (banner_types.json):

| id | code | description | previewForm | titleMaxLength | textMaxLength | channels |
|---|---|---|---|---|---|---|
| 1 | STORY | История | MOBILE_STORY | 100 | 500 | iOS, ANDROID |
| 2 | SMART_BANNER | Смарт баннер | MOBILE_BANNER | 250 | 1000 | iOS, ANDROID, WEB |

Совместимость канала с типом баннера проверяется по колонке `channels` типа баннера.

<a id="sec-1-3"></a>
### 1.3 Сегменты (segment_types.json + segments.json)

Типы (8): `GEO_CITY, GEO_REGION, AGE, GENDER, INTEREST, PRODUCT, CHANNEL, BASIC`.

Сегменты (40, выбирать можно только `state=ACTIVE`; сегмент `SEG_DRAFT_WINTER` — `NEW` с count 0, в выборе не участвует):

| code | name | type | state | count |
|---|---|---|---|---|
| CITY_MSK | Москва | GEO_CITY | ACTIVE | 13 000 000 |
| CITY_SPB | Санкт-Петербург | GEO_CITY | ACTIVE | 5 600 000 |
| CITY_NVS | Новосибирск | GEO_CITY | ACTIVE | 1 200 000 |
| CITY_KZN | Казань | GEO_CITY | ACTIVE | 900 000 |
| CITY_EKB | Екатеринбург | GEO_CITY | ACTIVE | 1 100 000 |
| CITY_SLD | Сочи | GEO_CITY | ACTIVE | 400 000 |
| REGION_MOS_OBL | Московская область | GEO_REGION | ACTIVE | 8 500 000 |
| REGION_LEN_OBL | Ленинградская область | GEO_REGION | ACTIVE | 3 200 000 |
| REGION_KRD_KRAI | Краснодарский край | GEO_REGION | ACTIVE | 4 200 000 |
| REGION_SVD_OBL | Свердловская область | GEO_REGION | ACTIVE | 3 100 000 |
| AGE_18_25 | Возраст 18–25 | AGE | ACTIVE | 9 000 000 |
| AGE_26_45 | Возраст 26–45 | AGE | ACTIVE | 24 000 000 |
| AGE_46_60 | Возраст 46–60 | AGE | ACTIVE | 18 000 000 |
| AGE_60_PLUS | Возраст 60+ | AGE | ACTIVE | 9 500 000 |
| MALE | Мужской пол | GENDER | ACTIVE | 34 000 000 |
| FEMALE | Женский пол | GENDER | ACTIVE | 42 000 000 |
| INTRS_FOOD | Еда | INTEREST | ACTIVE | 4 210 000 |
| INTRS_TRAVEL | Путешествия | INTEREST | ACTIVE | 6 800 000 |
| INTRS_SPORT | Спорт | INTEREST | ACTIVE | 5 300 000 |
| INTRS_CARS | Автомобили | INTEREST | ACTIVE | 7 400 000 |
| INTRS_HOME_REPAIR | Дом и ремонт | INTEREST | ACTIVE | 3 900 000 |
| INTRS_CHILDREN | Дети | INTEREST | ACTIVE | 6 100 000 |
| INTRS_CINEMA | Кино | INTEREST | ACTIVE | 8 700 000 |
| PRODUCT_CC | Кредитная карта | PRODUCT | ACTIVE | 5 200 000 |
| PRODUCT_DC | Дебетовая карта | PRODUCT | ACTIVE | 32 000 000 |
| PRODUCT_DEP | Вклад | PRODUCT | ACTIVE | 8 100 000 |
| PRODUCT_PREMIUM | Премиальная карта | PRODUCT | ACTIVE | 1 250 000 |
| PRODUCT_MORTGAGE | Ипотека | PRODUCT | ACTIVE | 2 100 000 |
| PRODUCT_AUTO_LOAN | Автокредит | PRODUCT | ACTIVE | 890 000 |
| PRODUCT_INSURANCE | Страхование | PRODUCT | ACTIVE | 4 600 000 |
| PRODUCT_SUBSCRIPTION | Подписки | PRODUCT | ACTIVE | 9 300 000 |
| CHANNEL_VIP | Канал VIP | CHANNEL | ACTIVE | 350 000 |
| CHANNEL_MASS | Массовый канал | CHANNEL | ACTIVE | 50 000 000 |
| CHANNEL_MID | Средний канал | CHANNEL | ACTIVE | 12 500 000 |
| CHANNEL_NEW_USER | Новые пользователи приложения | CHANNEL | ACTIVE | 2 900 000 |
| EXC_MORATORIUM | Исключение. Мораторий | BASIC | ACTIVE | 2 000 000 |
| EXC_UNSUBSCRIBED | Исключение. Отписались от рекламы | BASIC | ACTIVE | 15 000 000 |
| EXC_OVERCOMMUNICATED | Исключение. Перекоммуницированы | BASIC | ACTIVE | 7 600 000 |
| EXC_EMPLOYEES | Исключение. Сотрудники банка | BASIC | ACTIVE | 250 000 |
| SEG_DRAFT_WINTER | Черновик. Зимняя кампания | BASIC | NEW | 0 |

<a id="sec-1-4"></a>
### 1.4 Места показа (places.json)

| id | code | description | defaultBanner | state |
|---|---|---|---|---|
| 1 | mainScreenStories | Промо-блок на главном экране | STORY | ACTIVE |
| 2 | mainScreenSmartBanner | Смарт-баннер на главном | SMART_BANNER | ACTIVE |
| 3 | catalogPromo | Промо-баннер в каталоге | SMART_BANNER | ACTIVE |
| 4 | oldStoriesSlot | Архивный сторис-слот | STORY | INACTIVE |
| 5 | paymentsScreenBanner | Баннер на экране платежей | SMART_BANNER | ACTIVE |
| 6 | historyScreenBanner | Баннер на экране истории операций | SMART_BANNER | ACTIVE |
| 7 | depositScreenPromo | Промо на экране вкладов | SMART_BANNER | ACTIVE |
| 8 | oldCatalogSlot | Слот каталога до редизайна | SMART_BANNER | INACTIVE |

---

<a id="sec-2"></a>
## 2. Кампания 101 «Премиальная карта: осенняя акция» (DRAFT, полный payload)

<a id="sec-2-1"></a>
### 2.1 Создание — CampaignInfoDto

```json
POST /campaigns
{
  "name": "Премиальная карта: осенняя акция",
  "marketingName": "Осень с премиальной картой",
  "startDate": "2026-11-05", "startTime": "10:00",
  "endDate": "2026-12-31", "endTime": "23:59",
  "topic": {"value": "SALES", "label": "Продажи"},
  "tags": [{"value": 4, "label": "Карты"}, {"value": 3, "label": "Скидки"}],
  "keywords": "карта;премиум;кэшбэк",
  "audienceType": "SEGMENTED",
  "weight": 10.0,
  "initialCtr": 15.0,
  "places": [{"value": 2, "label": "mainScreenSmartBanner"}]
}
```

Ответ: `{"id": 101, "state": "DRAFT", "published": false, "author": "ivanov.p"}` — дефолты (`weight=0`, `initialCtr=15`) применяются на бэкенде, если не переданы.

<a id="sec-2-2"></a>
### 2.2 Сегменты

```json
PUT /campaigns/101/segments
{"included": ["CHANNEL_VIP", "CITY_MSK"], "excluded": ["EXC_UNSUBSCRIBED"]}
```

Семантика: клиент из VIP-канала ИЛИ из Москвы, кроме отписавшихся от рекламы.

<a id="sec-2-3"></a>
### 2.3 Баннер 201 (SMART_BANNER) — полный JSON

```json
POST /campaigns/101/banners
{
  "name": "Смарт-баннер осенний",
  "bannerTypeId": 2,
  "content": {
    "title": "Премиальная карта — осенняя акция",
    "titleStyle": {"fontSize": 17, "fontWeight": "medium", "textColor": "#000000FF"},
    "text": "Повышенный кэшбэк в кафе и на заправках до 31 декабря",
    "textStyle": {"fontSize": 13, "fontWeight": "medium", "textColor": "#808080FF"},
    "background": {"color": "#E8FAFFFF"},
    "image": {"url": "https://media.hackathon-crm.example/CAMPAIGNS/3f2b8c14-7a91-4e5d-b6c8-12f0a9d3e471"},
    "buttonName": "Оформить",
    "actionType": "externalLink",
    "link": {"iOS": "mobilebank://products/card/premium",
             "android": "mobilebank://products/card/premium",
             "web": "https://promo.hackathon-crm.example/promo/premium-autumn"},
    "voiceOver": "Баннер: премиальная карта, повышенный кэшбэк"
  }
}
```

<a id="sec-2-4"></a>
### 2.4 Контент 301 (PROMO) — полный JSON

```json
POST /campaigns/101/contents
{
  "name": "Промо-экран: премиальная карта",
  "contentType": "PROMO",
  "content": {
    "role": "promo",
    "component": {
      "role": "linearContainer",
      "axis": "v",
      "aligns": "lt",
      "style": {"backgroundColor": "#FFFFFFFF"},
      "components": [
        {"role": "image",
         "url": "https://media.hackathon-crm.example/CAMPAIGNS/c261bb69-6d13-49a3-9707-4f698f2b5d28",
         "aspectRatio": 2.0},
        {"role": "text", "format": "html", "text": "<b>Кэшбэк 10%</b> в кафе и на заправках",
         "textStyle": {"fontSize": 24, "fontWeight": "semi-bold", "textColor": "#000014FF"}},
        {"role": "text", "format": "none",
         "text": "Оформите премиальную карту и получайте повышенный кэшбэк до 31 декабря",
         "textStyle": {"fontSize": 15, "fontWeight": "regular", "textColor": "#00001499"}},
        {"role": "button", "text": "Оформить карту", "actionType": "externalLink",
         "link": {"iOS": "mobilebank://products/card/premium",
                  "android": "mobilebank://products/card/premium"},
         "textStyle": {"fontSize": 15, "fontWeight": "medium", "textColor": "#FFFFFFFF"},
         "style": {"backgroundColor": "#1244A8FF"}}
      ]
    }
  }
}
```

<a id="sec-2-5"></a>
### 2.5 Креативы (два канала)

```json
POST /campaigns/101/creatives
{"name": "Креатив Android", "bannerId": 201, "contentId": 301, "channelCode": "ANDROID"}
```
```json
POST /campaigns/101/creatives
{"name": "Креатив iOS", "bannerId": 201, "contentId": 301, "channelCode": "iOS"}
```

Warnings кампании 101: пусто.

---

<a id="sec-3"></a>
## 3. Кампания 102 «Кэшбэк за автоплатежи» (ACTIVE — полный цикл)

Шапка: `topic=SALES`, тег Промо(2), `keywords="автоплатеж;кэшбэк"`, даты 2026-10-10 00:00 → 2026-11-30 23:59, `audienceType=ALL_USERS`, `weight=5`, `initialCtr=15`.

- Место: 1 (mainScreenStories) → баннер 202 STORY (`openSmartLink`).
- Контент 302 PROMO: кнопка `doneCampaign` **без link** (правило: closeCampaign/doneCampaign → ссылки запрещены).
- Креатив 403: banner 202 + content 302, iOS.
- Жизненный цикл (все переходы валидны, log — `mocks/lifecycle_transitions.json`):

| Дата | State | Действие (роль) |
|---|---|---|
| 2026-10-05 | DRAFT | создана (ivanov.p) |
| 2026-10-06 | ON_MODERATION | to-moderation |
| 2026-10-07 | NEEDS_WORK | decline (petrova.m, «Заголовок баннера не отражает суть акции») → правки |
| 2026-10-08 | ON_MODERATION | to-moderation повторно |
| 2026-10-09 | APPROVED | approve (petrova.m) |
| 2026-10-10 | ACTIVE | activate → экспорт в CBRO успешен (`published=true`) |

Поле комментария модератора у кампании отсутствует: комментарий от 07.10 хранится только в журнале аудита (`lifecycle_transitions.json`) ([§2.3](task.md#sec-2-3) task.md).

---

<a id="sec-4"></a>
## 4. Кампания 103 «Сомелье: подбор вина» (минимальный payload, ON_MODERATION)

Все необязательные поля отсутствуют (marketingName, endDate/endTime, tags, keywords):

```json
POST /campaigns
{
  "name": "Сомелье: подбор вина",
  "startDate": "2026-11-15", "startTime": "12:00",
  "topic": {"value": "RECOMMENDATION", "label": "Рекомендации"},
  "audienceType": "ALL_USERS",
  "places": [{"value": 3, "label": "catalogPromo"}]
}
```

- Баннер 203 SMART_BANNER — минимальный валидный JSON с заголовком: `{"title": "Сомелье: подбор вина", "actionType": "default"}`.
- Креатив 404 **без контента** (`contentId: null`) — валидно.
- Сегменты: не заданы (валидно для ALL_USERS).
- Warnings: `["У кампании отсутствуют теги"]` — не блокируют, кампания отправлена на модерацию.

---

<a id="sec-5"></a>
## 5. Кампания 104 «Ипотека: ставка 4,9%» (NEEDS_WORK — цикл исправления)

Шапка: даты 2026-11-01 → 2026-12-15, `topic=SALES`, тегов нет, `audienceType=SEGMENTED`, weight 0 (дефолт). Места: **1 и 4** (4 — INACTIVE). Баннеров и креативов нет.

```json
PUT /campaigns/104/segments
{"included": ["AGE_26_45", "CITY_MSK"], "excluded": ["EXC_MORATORIUM"]}
```

Жизненный цикл: создана 20.10 → to-moderation 21.10 → decline 22.10 (petrova.m, комментарий: *«Креативы настроены не для всех мест показа; добавьте теги кампании»*) → `NEEDS_WORK`.

Warnings (`GET /campaigns/104/warnings`):

```json
{"errors": [], "warnings": [
  "Не для всех мест показа настроены креативы",
  "Некоторые места показа деактивированы",
  "У кампании отсутствуют теги"
]}
```

Дальнейший путь кампании: правки (баннер/креатив для места 1, убирать место 4, добавить теги — `NEEDS_WORK` остаётся редактируемым, state при правках не меняется) → повторный `to-moderation`.

---

<a id="sec-6"></a>
## 6. Кампании 106–115 (дополнительное разнообразие)

<a id="sec-6-1"></a>
### 6.1 Активные кампании с правками

- **106 «Путешествия: кэшбэк на отели»** (ACTIVE_EDITING, published=true): 3 места (1, 5, 6), STORY-креативы для iOS и Android (406/407), SMART-места не покрыты → warning `PLACE_NO_CREATIVE`.
- **109 «Мобильная подписка: месяц в подарок»** (ACTIVE_EDITING, published=true): единственное место 5 покрыто креативом 410, теги есть → warnings пустые. Контент 306: кнопка `doneCampaign`. После публикации кампания редактировалась — state перешёл в ACTIVE_EDITING, показ не прерывался.

<a id="sec-6-2"></a>
### 6.2 Одобренная и ожидающая активации

- **107 «Страхование выезда за рубеж»** (APPROVED): веб-креатив 409 (SMART_BANNER допускает WEB) + iOS-креатив 408; контент 305 с тремя типами ссылок.

<a id="sec-6-3"></a>
### 6.3 Разные статусы модерации

- **110 «Автокредит: ставка от 7,9%»** (ON_MODERATION): места 1 и 7, креатив только сторис (411) → warning `PLACE_NO_CREATIVE`. Warnings не блокируют одобрение.
- **115 «Подписка на фильмы: первый месяц 1₽»** (NEEDS_WORK): отклонена по содержанию креатива; контент 311 с кнопкой `closeCampaign` (ссылки запрещены).

<a id="sec-6-4"></a>
### 6.4 Черновики разной степени готовности

- **108 «Курс по финансовой грамотности»** (DRAFT): минимальный баннер 208 (без text и кнопки), ALL_USERS.
- **111 «Зимний марафон скидок»** (DRAFT): конец в январе 2027, тема EVENT, вес 12.0; два баннера (211 STORY, 216 SMART_BANNER); креативы iOS 412 (с контентом 308) и Web 413 без контента (SMART_BANNER+WEB валидно).
- **112 «Онбординг в инвестиции»** (DRAFT): исключение-продукт (`PRODUCT_SUBSCRIPTION`), 2 места одного типа.
- **113 «Летний кешбэк: архив»** (DRAFT): единственное место 8 — INACTIVE, креативов нет → 2 warnings (тег есть — warning по тегам не выдаётся).

<a id="sec-6-5"></a>
### 6.5 Остановленная

- **114 «Дебетовая карта: бесплатные переводы»** (STOPPED, published=false): полный цикл до активации + stop 26.10 (см. log). Состояние заморожено: не редактируется и не возобновляется в MVP.

---

<a id="sec-7"></a>
## 7. Валидации и warnings

<a id="sec-7-1"></a>
### 7.1 Каталог ошибок и warnings

Единый источник истины — `mocks/validation_rules.json` (43 ошибки, 3 warning).

<a id="sec-7-2"></a>
### 7.2 Правило покрытия мест креативами (для warning `PLACE_NO_CREATIVE`)

Место показа считается покрытым, если у кампании есть ≥1 креатив, чей баннер имеет тип `code == place.defaultBanner` (канальная совместимость уже проверена на уровне креатива). Пример: место `mainScreenStories` (STORY) покрыто креативом баннера типа STORY; если в кампании только SMART_BANNER-креативы — место не покрыто (см. кампанию 106). Место без `defaultBanner` (созданное через `POST /places`) считается покрытым — правило неприменимо.

<a id="sec-7-3"></a>
### 7.3 Warnings по кампаниям

Файл `mocks/campaign_warnings.json` — предвычисленные warnings для 7 кампаний (103, 104, 106, 108, 110, 113 и пустые для 109). Warnings хранятся строками; тексты совпадают с сообщениями каталога `mocks/validation_rules.json`, коды — справочные (для маппинга в UI).

---

<a id="sec-8"></a>
## 8. CBRO-экспорт (заглушка, cbro_export.json)

```json
POST /mock/cbro/export
{"campaignId": 102}
→ success: {"status": "OK", "exportedAt": "2026-10-10T00:00:05"}
```

Правила: activate доступен только из state=APPROVED; при успехе `state=ACTIVE, published=true`. Ошибки брокера в MVP не эмулируются — заглушка всегда возвращает успех; ассистент обрабатывает только ошибки валидации бэкенда ([§4](task.md#sec-4) task.md).

---

<a id="sec-9"></a>
## 9. Чек-лист консистентности данных

1. **Уникальность**: CAMPAIGN.NAME (14 имён различны), PLACE.CODE, (campaign, bannerId, channelCode) в креативах.
2. **JSON**: баннер и контент — по схемам [§2.6](task.md#sec-2-6)–[§2.7](task.md#sec-2-7) `task.md` (actionType из enum; link обязателен при externalLink/openSmartLink и запрещён при closeCampaign/doneCampaign; у text обязателен format; у image обязателен url; у promo ровно один корневой linearContainer).
3. **Кросс-поля**: SEGMENTED ⇒ ≥1 включённый сегмент; ALL_USERS ⇒ списки сегментов пусты (в данных: 102, 103, 108, 113, 115; PUT с непустыми списками → ошибка `SEGMENTS_FORBIDDEN_FOR_ALL_USERS`).
4. **Ссылки на справочники**: places/banners/creatives/segments ссылаются только на сущности из [§1](#sec-1) (id и code валидны); сегменты включения/исключения — в состоянии ACTIVE (`SEG_DRAFT_WINTER` нигде не используется).
5. **Совместимость**: creative(channel) ∈ channels(bannerType); креатив STORY+WEB — ошибка (в данных таких нет; WEB-креативы 409/413 — только SMART_BANNER).
6. **Жизненный цикл**: состояния — только из таблицы `task.md` [§2.3](task.md#sec-2-3); редактирование разрешено в `DRAFT`, `NEEDS_WORK`, `APPROVED`, `ACTIVE`, `ACTIVE_EDITING` и запрещено в `ON_MODERATION`/`STOPPED` (`UPDATE_NOT_ALLOWED`); правка `APPROVED` снимает одобрение (→ `DRAFT`); правка `ACTIVE` → `ACTIVE_EDITING` (106, 109); decline — только после to-moderation и с комментарием (комментарий хранится только в журнале аудита, у кампании поля нет); approve — только после to-moderation; активация — только из `APPROVED`, при успехе `published=true`; stop — только при `published=true` и снимает флаг (114); удаление — из `DRAFT`/`NEEDS_WORK` при `published=false`. Инвариант флага: `published=true` только у кампаний, хотя бы раз активированных и не остановленных (в моках — 102, 106, 109); переходы модерации флаг не меняют. Переходы из недопустимых состояний → ошибки `*_NOT_ALLOWED`, действия не по роли → `ROLE_FORBIDDEN`.
7. **Даты**: START_DATE < END_DATE (end может быть null); у активных кампаний 102, 106, 109 today (27.10) ∈ [start, end]; у STOPPED 114 период тоже пересекает today (остановлена вручную).
8. **Медиа**: `image.url` (баннер) и `url` (image-компонент контента) — произвольные валидные https-ссылки на изображение. Ссылки на `media.hackathon-crm.example` синтетические (домен `.example` зарезервирован) и не резолвятся — для превью подставляйте собственные изображения ([§10.9](task.md#sec-10-9) task.md).
9. **Warnings**: соответствуют правилу [§7.2](#sec-7-2) (проверено для всех 14 кампаний).
