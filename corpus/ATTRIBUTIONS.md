# Corpus attributions (real-derived items)

Every `origin: "derived"` corpus item redistributes a *modified* excerpt of a real,
permissively-licensed source. This file records the attribution and license for
each, as required by those licenses. Per-item provenance also lives in each
`meta.json` `source` block; this file is the consolidated view.

Only licenses that permit modification + redistribution inside a CC-BY-4.0 corpus
are used (see `../docs/corpus-construction.md` for the allow-list). Copyleft
(GPL/LGPL/MPL) and CC-BY-SA/-NC/-ND sources are excluded.

**Corpus totals:** 60 items — 19 code, 23 paper, 18 spec. Of these, 3 are
synthetic (`*-0001`) and 57 are derived from the sources below.

## Code (`code/`)

| Item | Source | Author / owner | License | Pinned ref |
|---|---|---|---|---|
| `code-0002` | [more-itertools `divide`](https://github.com/more-itertools/more-itertools/blob/ed86a1528aa015f219f8d3385ea2ebd3f63a5212/more_itertools/more.py#L2049) | Erik Rose & more-itertools contributors | MIT | `ed86a15` |
| `code-0003` | [CPython `bisect_right`](https://github.com/python/cpython/blob/1fd603fad20187496619930e5b74aa7690425926/Lib/bisect.py#L21) | Python Software Foundation | PSF-2.0 | `1fd603f` |
| `code-0004` | [CPython `statistics.median`](https://github.com/python/cpython/blob/55a09ed4227eecbc4a3880637c2250bfc05858ef/Lib/statistics.py#L328) | Python Software Foundation | PSF-2.0 | `55a09ed` |
| `code-0005` | [TheAlgorithms `roman_to_int`](https://github.com/TheAlgorithms/Python/blob/e3b01ecd1267d39d49b99db9676a653ff197db62/conversions/roman_numerals.py#L18) | TheAlgorithms/Python contributors | MIT | `e3b01ec` |
| `code-0006` | [TheAlgorithms `int_to_roman`](https://github.com/TheAlgorithms/Python/blob/e3b01ecd1267d39d49b99db9676a653ff197db62/conversions/roman_numerals.py#L44) | TheAlgorithms/Python contributors | MIT | `e3b01ec` |
| `code-0007` | [TheAlgorithms `collatz_sequence`](https://github.com/TheAlgorithms/Python/blob/e3b01ecd1267d39d49b99db9676a653ff197db62/maths/collatz_sequence.py) | TheAlgorithms/Python contributors | MIT | `e3b01ec` |
| `code-0008` | [TheAlgorithms `sum_of_digits`](https://github.com/TheAlgorithms/Python/blob/e3b01ecd1267d39d49b99db9676a653ff197db62/maths/sum_of_digits.py) | TheAlgorithms/Python contributors | MIT | `e3b01ec` |
| `code-0009` | [TheAlgorithms `factorial`](https://github.com/TheAlgorithms/Python/blob/e3b01ecd1267d39d49b99db9676a653ff197db62/maths/factorial.py#L6) | TheAlgorithms/Python contributors | MIT | `e3b01ec` |
| `code-0010` | [TheAlgorithms `bubble_sort`](https://github.com/TheAlgorithms/Python/blob/e3b01ecd1267d39d49b99db9676a653ff197db62/sorts/bubble_sort.py#L4) | TheAlgorithms/Python contributors | MIT | `e3b01ec` |
| `code-0011` | [TheAlgorithms `fibonacci`](https://github.com/TheAlgorithms/Python/blob/e3b01ecd1267d39d49b99db9676a653ff197db62/maths/fibonacci.py#L65) | TheAlgorithms/Python contributors | MIT | `e3b01ec` |
| `code-0012` | [TheAlgorithms `binary_to_decimal`](https://github.com/TheAlgorithms/Python/blob/e3b01ecd1267d39d49b99db9676a653ff197db62/conversions/binary_to_decimal.py) | TheAlgorithms/Python contributors | MIT | `e3b01ec` |
| `code-0013` | [TheAlgorithms `binary_exponentiation`](https://github.com/TheAlgorithms/Python/blob/e3b01ecd1267d39d49b99db9676a653ff197db62/maths/binary_exponentiation.py#L53) | TheAlgorithms/Python contributors | MIT | `e3b01ec` |
| `code-0014` | [TheAlgorithms `decimal_to_hexadecimal`](https://github.com/TheAlgorithms/Python/blob/e3b01ecd1267d39d49b99db9676a653ff197db62/conversions/decimal_to_hexadecimal.py#L24) | TheAlgorithms/Python contributors | MIT | `e3b01ec` |
| `code-0015` | [TheAlgorithms `insertion_sort`](https://github.com/TheAlgorithms/Python/blob/e3b01ecd1267d39d49b99db9676a653ff197db62/sorts/insertion_sort.py#L27) | TheAlgorithms/Python contributors | MIT | `e3b01ec` |
| `code-0016` | [TheAlgorithms `selection_sort`](https://github.com/TheAlgorithms/Python/blob/e3b01ecd1267d39d49b99db9676a653ff197db62/sorts/selection_sort.py#L1) | TheAlgorithms/Python contributors | MIT | `e3b01ec` |
| `code-0017` | [TheAlgorithms `count_number_of_one_bits`](https://github.com/TheAlgorithms/Python/blob/e3b01ecd1267d39d49b99db9676a653ff197db62/bit_manipulation/count_number_of_one_bits.py#L33) | TheAlgorithms/Python contributors | MIT | `e3b01ec` |
| `code-0018` | [TheAlgorithms `find_max`](https://github.com/TheAlgorithms/Python/blob/e3b01ecd1267d39d49b99db9676a653ff197db62/maths/find_max.py#L4) | TheAlgorithms/Python contributors | MIT | `e3b01ec` |
| `code-0019` | [TheAlgorithms `gnome_sort`](https://github.com/TheAlgorithms/Python/blob/e3b01ecd1267d39d49b99db9676a653ff197db62/sorts/gnome_sort.py#L16) | TheAlgorithms/Python contributors | MIT | `e3b01ec` |

## Specs / configs (`spec/`)

| Item | Source | Author / owner | License | Pinned ref |
|---|---|---|---|---|
| `spec-0002` | [awesome-compose react-express-mysql](https://github.com/docker/awesome-compose/blob/30f4b7f6a6c3b0c0ecf4d4efb0de203c48d11562/react-express-mysql/compose.yaml) | docker/awesome-compose contributors | CC0-1.0 | `30f4b7f` |
| `spec-0003` | [awesome-compose nginx-golang-postgres](https://github.com/docker/awesome-compose/blob/30f4b7f6a6c3b0c0ecf4d4efb0de203c48d11562/nginx-golang-postgres/compose.yaml) | docker/awesome-compose contributors | CC0-1.0 | `30f4b7f` |
| `spec-0004` | [awesome-compose nginx-flask-mysql](https://github.com/docker/awesome-compose/blob/30f4b7f6a6c3b0c0ecf4d4efb0de203c48d11562/nginx-flask-mysql/compose.yaml) | docker/awesome-compose contributors | CC0-1.0 | `30f4b7f` |
| `spec-0005` | [awesome-compose prometheus-grafana](https://github.com/docker/awesome-compose/blob/30f4b7f6a6c3b0c0ecf4d4efb0de203c48d11562/prometheus-grafana/compose.yaml) | docker/awesome-compose contributors | CC0-1.0 | `30f4b7f` |
| `spec-0006` | [awesome-compose wordpress-mysql](https://github.com/docker/awesome-compose/blob/30f4b7f6a6c3b0c0ecf4d4efb0de203c48d11562/wordpress-mysql/compose.yaml) | docker/awesome-compose contributors | CC0-1.0 | `30f4b7f` |
| `spec-0007` | [awesome-compose gitea-postgres](https://github.com/docker/awesome-compose/blob/30f4b7f6a6c3b0c0ecf4d4efb0de203c48d11562/gitea-postgres/compose.yaml) | docker/awesome-compose contributors | CC0-1.0 | `30f4b7f` |
| `spec-0008` | [kubernetes/website run-my-nginx + nginx-svc](https://github.com/kubernetes/website/blob/0640ccf95db0469f884f37fb856951a1a182c9f1/content/en/examples/service/networking/run-my-nginx.yaml) | The Kubernetes Authors | CC-BY-4.0 | `0640ccf` |
| `spec-0009` | [kubernetes/website pod-single-configmap-env-variable](https://github.com/kubernetes/website/blob/0640ccf95db0469f884f37fb856951a1a182c9f1/content/en/examples/pods/pod-single-configmap-env-variable.yaml) | The Kubernetes Authors | CC-BY-4.0 | `0640ccf` |
| `spec-0010` | [kubernetes/website secret-envars-pod](https://github.com/kubernetes/website/blob/0640ccf95db0469f884f37fb856951a1a182c9f1/content/en/examples/pods/inject/secret-envars-pod.yaml) | The Kubernetes Authors | CC-BY-4.0 | `0640ccf` |
| `spec-0011` | [awesome-compose spring-postgres](https://github.com/docker/awesome-compose/blob/30f4b7f6a6c3b0c0ecf4d4efb0de203c48d11562/spring-postgres/compose.yaml) | docker/awesome-compose contributors | CC0-1.0 | `30f4b7f` |
| `spec-0012` | [kubernetes/website pv-pod](https://github.com/kubernetes/website/blob/0640ccf95db0469f884f37fb856951a1a182c9f1/content/en/examples/pods/storage/pv-pod.yaml) | The Kubernetes Authors | CC-BY-4.0 | `0640ccf` |
| `spec-0013` | [awesome-compose nextcloud-postgres](https://github.com/docker/awesome-compose/blob/30f4b7f6a6c3b0c0ecf4d4efb0de203c48d11562/nextcloud-postgres/compose.yaml) | docker/awesome-compose contributors | CC0-1.0 | `30f4b7f` |
| `spec-0014` | [awesome-compose react-express-mongodb](https://github.com/docker/awesome-compose/blob/30f4b7f6a6c3b0c0ecf4d4efb0de203c48d11562/react-express-mongodb/compose.yaml) | docker/awesome-compose contributors | CC0-1.0 | `30f4b7f` |
| `spec-0015` | [awesome-compose nginx-wsgi-flask](https://github.com/docker/awesome-compose/blob/30f4b7f6a6c3b0c0ecf4d4efb0de203c48d11562/nginx-wsgi-flask/compose.yaml) | docker/awesome-compose contributors | CC0-1.0 | `30f4b7f` |
| `spec-0016` | [awesome-compose elasticsearch-logstash-kibana](https://github.com/docker/awesome-compose/blob/30f4b7f6a6c3b0c0ecf4d4efb0de203c48d11562/elasticsearch-logstash-kibana/compose.yaml) | docker/awesome-compose contributors | CC0-1.0 | `30f4b7f` |
| `spec-0017` | [awesome-compose nginx-flask-mongo](https://github.com/docker/awesome-compose/blob/30f4b7f6a6c3b0c0ecf4d4efb0de203c48d11562/nginx-flask-mongo/compose.yaml) | docker/awesome-compose contributors | CC0-1.0 | `30f4b7f` |
| `spec-0018` | [kubernetes/website web.yaml](https://github.com/kubernetes/website/blob/0640ccf95db0469f884f37fb856951a1a182c9f1/content/en/examples/application/web/web.yaml) | The Kubernetes Authors | CC-BY-4.0 | `0640ccf` |

## Papers / reports (`paper/`)

| Item | Source | Author / owner | License | Pinned ref |
|---|---|---|---|---|
| `paper-0002` | [CBO Monthly Budget Review, FY2025 Summary](https://www.cbo.gov/publication/61307) | Congressional Budget Office (U.S. Gov work) | public-domain | `pub-61307` |
| `paper-0003` | [Our World in Data — Extreme poverty](https://ourworldindata.org/extreme-poverty) | Our World in Data (Roser, Hasell, et al.) | CC-BY-4.0 | retrieved 2026-07-05 |
| `paper-0004` | [Our World in Data — Literacy](https://ourworldindata.org/literacy) | Our World in Data (Roser, Ortiz-Ospina) | CC-BY-4.0 | retrieved 2026-07-05 |
| `paper-0005` | [Our World in Data — Life expectancy](https://ourworldindata.org/life-expectancy) | Our World in Data (Roser, Ortiz-Ospina, Ritchie) | CC-BY-4.0 | retrieved 2026-07-05 |
| `paper-0006` | [Our World in Data — Hunger & undernourishment](https://ourworldindata.org/hunger-and-undernourishment) | Our World in Data (Roser, Ritchie) | CC-BY-4.0 | retrieved 2026-07-05 |
| `paper-0007` | [Our World in Data — Maternal mortality](https://ourworldindata.org/maternal-mortality) | Our World in Data (Roser, Ritchie, Dadonaite) | CC-BY-4.0 | retrieved 2026-07-05 |
| `paper-0008` | [Our World in Data — Vaccination](https://ourworldindata.org/vaccination) | Our World in Data (Roser, Ritchie, Dattani) | CC-BY-4.0 | retrieved 2026-07-05 |
| `paper-0009` | [Our World in Data — CO₂ emissions](https://ourworldindata.org/co2-emissions) | Our World in Data (Ritchie, Roser, Rosado) | CC-BY-4.0 | retrieved 2026-07-05 |
| `paper-0010` | [Our World in Data — Clean water access](https://ourworldindata.org/water-access) | Our World in Data (Ritchie, Roser) | CC-BY-4.0 | retrieved 2026-07-05 |
| `paper-0011` | [Our World in Data — Sanitation](https://ourworldindata.org/sanitation) | Our World in Data (Ritchie, Spooner, Roser) | CC-BY-4.0 | retrieved 2026-07-05 |
| `paper-0012` | [Our World in Data — Urbanization](https://ourworldindata.org/urbanization) | Our World in Data (Ritchie, Roser) | CC-BY-4.0 | retrieved 2026-07-05 |
| `paper-0013` | [Our World in Data — World population growth](https://ourworldindata.org/world-population-growth) | Our World in Data (Ritchie, Rodes-Guirao, Roser) | CC-BY-4.0 | retrieved 2026-07-05 |
| `paper-0014` | [Our World in Data — Renewable energy](https://ourworldindata.org/renewable-energy) | Our World in Data (Ritchie, Roser, Rosado) | CC-BY-4.0 | retrieved 2026-07-05 |
| `paper-0015` | [Our World in Data — Famines](https://ourworldindata.org/famines) | Our World in Data (Hasell, Roser) | CC-BY-4.0 | retrieved 2026-07-05 |
| `paper-0016` | [Our World in Data — Obesity](https://ourworldindata.org/obesity) | Our World in Data (Ritchie, Roser) | CC-BY-4.0 | retrieved 2026-07-05 |
| `paper-0017` | [Our World in Data — Smoking](https://ourworldindata.org/smoking) | Our World in Data (Dattani, Ritchie, Roser) | CC-BY-4.0 | retrieved 2026-07-05 |
| `paper-0018` | [Our World in Data — Alcohol consumption](https://ourworldindata.org/alcohol-consumption) | Our World in Data (Ritchie, Roser) | CC-BY-4.0 | retrieved 2026-07-05 |
| `paper-0019` | [Our World in Data — Meat production](https://ourworldindata.org/meat-production) | Our World in Data (Ritchie, Rosado, Roser) | CC-BY-4.0 | retrieved 2026-07-05 |
| `paper-0020` | [Our World in Data — Financing healthcare](https://ourworldindata.org/financing-healthcare) | Our World in Data (Roser, Ortiz-Ospina) | CC-BY-4.0 | retrieved 2026-07-05 |
| `paper-0021` | [Our World in Data — Plastic pollution](https://ourworldindata.org/plastic-pollution) | Our World in Data (Ritchie, Roser) | CC-BY-4.0 | retrieved 2026-07-05 |
| `paper-0022` | [Our World in Data — Forest area](https://ourworldindata.org/forest-area) | Our World in Data (Ritchie, Roser) | CC-BY-4.0 | retrieved 2026-07-05 |
| `paper-0023` | [Our World in Data — Life expectancy](https://ourworldindata.org/life-expectancy) | Our World in Data (Roser, Ortiz-Ospina, Ritchie) | CC-BY-4.0 | retrieved 2026-07-05 |

> Note: defects in these items were introduced by the ReviewConverge authors for
> benchmarking; they are not bugs in the upstream projects/sources. For code, the
> upstream form of every mutated line is recorded in each defect's `rationale` in
> `defects.json`. For papers, the underlying figures are real (from the cited
> source) and any composed-prose caveat is noted in the item's `meta.json`; the
> numeric inconsistencies are authored, not attributable to the source.

## Synthetic items (no third-party source)

`code-0001`, `paper-0001`, and `spec-0001` are authored from scratch by the
ReviewConverge authors (CC-BY-4.0) as format exemplars; they carry
`origin: "synthetic"` and need no attribution. `paper-0001`'s "CLINSUM" dataset
and results are fictional (see its `meta.json`).
