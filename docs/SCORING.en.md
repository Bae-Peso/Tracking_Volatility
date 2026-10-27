# How the Forecast Volatility Score Is Calculated

[한국어](/docs/SCORING.md) | **English** | [日本語](/docs/SCORING.ja.md)

## Overview

The score shows, from 0 to 100, how closely the forecast made n days earlier (1–14) matched the same-day 22:00 forecast (d0). 100 means identical to d0; the lower the score, the more the forecast shifted. Observed values are not used. The code is in `accu_weather/daily.py` and `accu_weather/accuracy.py`; the full design notes are in [PLAN.md](PLAN.md) section 5.1.

1. Combine the 24 hourly forecasts into one daily row (for every n-days-ahead forecast, and for d0 in the same way).
2. Take the difference "n days ahead − d0" between the daily rows. For weather and precipitation probability, also compare the same times of day (3-hour blocks).
3. Convert each of the five items (temperature, feels-like temperature, precipitation probability, precipitation amount, weather) to 0–1. 0 = identical, 1 = differs by the threshold or more.
4. Multiply each of the five values by 0.2 and add them up to get the penalty. Score = 100 × (1 − penalty).
5. As soon as d0 arrives (right after the local 22:00 collection), compute the 14 rows for 1–14 days ahead for that date and store them in the `accuracy` table.

## Daily aggregation rules

Forecasts are fetched hourly and also stored as-is in 1-hour slots. However, places where hourly values are hard to display, such as the calendar, the day view and the daily unit of the graph, as well as the score calculation, need one value per date. So the 24 slots are combined into a separate one-row "daily value".

Daily values lean toward "the worst moment of the day". Only precipitation amount is summed.

| Item | 24 hours → one day |
| --- | --- |
| Max temperature / max feels-like | Maximum |
| Min temperature / min feels-like | Minimum |
| Precipitation (mm) | Sum |
| Precipitation probability (%) | Maximum |
| Weather | The code with the largest weather weight (on a tie, the higher code number) |
| Wind / visibility | Maximum / minimum (not used in the score) |

## Per-item difference and 0–1 normalization

The five items are split so that their effects on people do not overlap: temperature for heat and cold, feels-like for humidity, wind and sunshine, precipitation for getting wet, and weather for travel and safety. Each item is capped at 1 at its threshold (`min(…, 1)`).

| Item | Compared value | 0–1 score | Worst (1) when |
| --- | --- | --- | --- |
| Temperature | Max and min temperature difference | (\|max diff\| + \|min diff\|) / 2 ÷ 5 | Average difference of 5 °C or more |
| Feels-like | Max and min feels-like difference | Same formula as temperature | Average difference of 5 °C or more |
| Precipitation probability | Daily max probability difference + time-of-day difference (%p) | (0.5 × \|max diff\| + 0.5 × time-of-day diff) ÷ 100 | 0% ↔ 100% |
| Precipitation amount | Daily total mm, square-root scale | \|√forecast − √d0\| ÷ √10 | A difference as large as 0 mm ↔ 10 mm |
| Weather | Weight of the representative weather code + weights by time of day | 0.5 × \|weight(forecast) − weight(d0)\| + 0.5 × time-of-day diff | Clear (0) ↔ thunderstorm with heavy hail (1) |

- Why precipitation uses a square-root scale: 0 → 1 mm (you now need an umbrella) counts for more than 10 → 11 mm (it is raining either way) (0.32 vs 0.15), while differences in heavy rain do not shrink. √10 ≈ 3.16.

  | Change | 0 → 1 | 10 → 11 | 10 → 20 | 30 → 50 | 50 → 100 |
  | --- | --- | --- | --- | --- | --- |
  | 0–1 | 0.32 | 0.15 | 0.41 | 0.50 | 0.92 |

  A log scale (\|log(1+forecast) − log(1+d0)\| ÷ log(1+10)) was used before. Since it only looks at ratios, 10 → 20 mm scored 0.27 and 30 → 50 mm 0.21, even less than 0 → 1 mm (0.29), so it was replaced.
- Why feels-like is a separate item: even with the same temperature, a change in the humidity or wind forecast changes how it feels. It uses Open-Meteo `apparent_temperature`.
- Differences are stored in the DB with their sign (+ means the forecast was higher). Only the score uses absolute values.
- If any of the five values is missing, the score is empty (None).

## Comparing weather and precipitation probability by time of day

If only the daily representative values (the worst weather of the day, the daily max probability) are compared, a day whose representative value is unchanged has a difference of 0. For example, if the forecast n days ahead said "heavy rain for 2 hours" and d0 says "heavy rain for 20 hours", both are represented by heavy rain, so the weather difference is 0. The same happens when the rain moves from the morning to the evening. So these two items also compare the 1-hour slots.

1. Split the 24 hours into eight 3-hour blocks (00–02, 03–05, …). For each block, weather uses the largest weight and precipitation probability uses the maximum.
2. Take \|n days ahead − d0\| for each block and average over the 8 blocks (time-of-day difference).
3. Item value = 0.5 × daily representative difference + 0.5 × time-of-day difference.

| Case (heavy rain 0.45, overcast 0.05, thunderstorm 0.75) | Representative diff | Time-of-day diff | Weather value |
| --- | --- | --- | --- |
| d0 heavy rain 00–17 ↔ forecast heavy rain 00–02 | 0 | 5 blocks × 0.4 / 8 = 0.25 | 0.125 |
| d0 heavy rain 06–11 ↔ forecast heavy rain 15–20 | 0 | 4 blocks × 0.4 / 8 = 0.2 | 0.1 |
| d0 one-hour thunderstorm at 14:00 ↔ forecast overcast all day | 0.7 | 0.7 / 8 ≈ 0.09 | 0.39 |

- Why half and half: using only the time-of-day difference dilutes "was it dangerous at least once that day", such as a short thunderstorm, to one eighth. Using only the representative value makes changes in duration and timing 0, as above. Mixing the two catches both.
- Why 3-hour blocks: a forecast made days earlier can hardly get the hour of rain right. A shift of 1–2 hours within the same block counts as the same; only large changes such as morning ↔ evening count as a difference.
- The signed daily max probability difference is stored in `precip_prob_diff`, and the time-of-day difference in `precip_prob_hourly_diff` (%p). For weather, the mixed value is stored in `weather_diff`.
- Without 1-hour slots (no block present in both), only the representative difference is used.

## Weather weights (weather_weight.json)

A weather weight rates, from 0 to 1, how much that weather affects travel and safety. The amount of rain and the rain/snow split are already covered by the precipitation and temperature items, so the weather item looks only at what those miss: fog visibility, snowy roads, ice, gusts and thunderstorms.

**How the weights were set** ([`tools/weight_study.py`](tools/weight_study.py)): hourly forecasts for 28 days were fetched for 24 cities in various climate zones. Four risk factors were rated 0–1 for each hour and averaged per weather code.

| Factor | 0 | 1 |
| --- | --- | --- |
| Visibility | 5 km or more | 1 km or less |
| Snow | 0 cm/h snowfall | 1 cm or more per hour |
| Ice | Condition not met | 0.5 when precipitation falls at 1 °C or below |
| Gusts | 30 km/h | 70 km/h or more |

The four factors are combined with the formula below. It has the shape of "the probability that at least one is dangerous": one large factor is enough to raise the value, and overlapping factors raise it further. The wind that blows even on clear days (base) is subtracted so that clear = 0.

```
impact = 1 − (1 − visibility) × (1 − snow) × (1 − ice) × (1 − gusts)
weight = (mean impact for the code − base) / (1 − base)      base = mean impact of clear sky (code 0)
```

**Adjusted by judgment**: codes with almost no samples (freezing rain, heavy snow, thunderstorms with hail, etc.) were set by hand. Fog was lowered from the measured 0.99 to 0.8 (visibility is at its worst, but the road itself does not become dangerous). Thunderstorms were raised from 0.29 to 0.75 (lightning and power-outage risk is not in the data). Heavy rain was raised from 0.34 to 0.45 to keep the intensity order.

| Type | Codes and weights |
| --- | --- |
| Clear / cloudy | 0 clear sky 0, 1 mainly clear 0, 2 partly cloudy 0.05, 3 overcast 0.05 |
| Fog | 45 fog 0.8, 48 depositing rime fog 0.9 |
| Drizzle | 51 light 0.15, 53 moderate 0.25, 55 dense 0.35 |
| Freezing drizzle | 56 light 0.5, 57 dense 0.65 |
| Rain | 61 slight 0.35, 63 moderate 0.4, 65 heavy 0.45 |
| Freezing rain | 66 light 0.7, 67 heavy 0.9 |
| Snow | 71 slight 0.55, 73 moderate 0.7, 75 heavy 0.85, 77 snow grains 0.45 |
| Rain showers | 80 slight 0.4, 81 moderate 0.6, 82 violent 0.7 |
| Snow showers | 85 slight 0.55, 86 heavy 0.85 |
| Thunderstorm | 95 thunderstorm 0.75, 96 with slight hail 0.8, 97 heavy thunderstorm 0.9, 99 with heavy hail 1.0 |

The data covers one month in late October, so winter and rainy-season weather is scarce. The plan is to recompute with the same script once more data accumulates. Earlier versions used the area of a (type, intensity) coordinate, but different weather such as fog and light drizzle could end up with a difference of 0, so it was replaced.

## Total score and worked example

The total score is 100 minus the penalty, with the same weight of 0.2 on each of the five items.

```
score = 100 × (1 − 0.2 × (temperature + feels-like + probability + amount + weather))
```

Example: if a 3-days-ahead forecast and the same-day (d0) forecast for a date look like this, the score is 56.9. Assuming both keep the same weather and probability all day, the time-of-day difference equals the representative difference, so weather and probability use the representative difference as is.

| Item | 3 days ahead | d0 | Calculation | 0–1 |
| --- | --- | --- | --- | --- |
| Temperature | Max 20 °C / min 10 °C | 18 °C / 11 °C | (2 + 1) / 2 ÷ 5 | 0.30 |
| Feels-like | 19 °C / 8 °C | 16 °C / 9 °C | (3 + 1) / 2 ÷ 5 | 0.40 |
| Precipitation probability | 60% | 20% | 40 ÷ 100 | 0.40 |
| Precipitation amount | 5 mm | 0 mm | √5 ÷ √10 = 2.24 ÷ 3.16 | 0.71 |
| Weather | 63 rain (0.4) | 3 overcast (0.05) | \|0.4 − 0.05\| | 0.35 |
| **Total** | | | 2.16 × 0.2 = 0.43 | Score **56.9** |

The monthly and yearly views group these scores by (city, period, days ahead) and take the mean or median ([PLAN.md](PLAN.md) section 5.2).

## Settings

The item weights (0.2 × 5), thresholds (5 °C, 10 mm), the block size of the time-of-day comparison (`block_hours = 3`) and the share of the representative value (`peak_share = 0.5`) are in `[accuracy]` of `config.toml`, and the weather weights are in `weather_weight.json`. All of them are provisional and may be adjusted as data accumulates. After changing them, run `python3 -m accu_weather recompute` to recalculate everything.
