# 🚀 Enterprise Asynchronous FastAPI Task Manager

Production-ready asynchronous Python REST API built on top of **FastAPI**, featuring structural implementation of **SQLAlchemy 2.0 ORM**, explicit data validation using **Pydantic v2**, and containerized configuration powered by **Docker Compose & PostgreSQL 17**.

## 🏗️ Architectural Core Features
* **100% Non-Blocking Architecture:** Fully leveraged Python async/await paradigms across database IO boundaries via `asyncpg`.
* **SQLAlchemy 2.0 Modern ORM Mapping:** Utilizes type-safe `Mapped[]` declarations with explicit relational mapping constraints.
* **Automatic Schema Provisioning:** Integrates a contextual FastAPI lifecycle lifespan manager to initialize relational tables dynamically on startup.
* **Enterprise Middleware Injection:** Embedded custom operational HTTP interceptors calculating compute latency pipelines and injecting structural audit headers (`X-Process-Time-Seconds`).
* **Granular Validation Layer:** Implements regex constraints, path assertions, query data constraints, and explicit serialization responses.

---

## 🗺️ System Endpoint Blueprints

### System Monitoring
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/health` | Measures live network ping latencies directly against PostgreSQL database layers. |

### User Profiles
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/users` | Registers unique system identities into relational state stores. |
| `GET` | `/users` | Queries paginated systemic profiles nested cleanly alongside owned operational tasks. |

### Business Tasks
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/tasks` | Provisions transactional task records linked strictly to registered user ids. |
| `GET` | `/tasks/{task_id}` | Captures specialized descriptive details of specified individual tasks. |
| `PATCH` | `/tasks/{task_id}` | Performs selective field mutations safely without resetting metadata layers. |
| `DELETE` | `/tasks/{task_id}` | Purges specific task tracking data entries instantly. |

---

## 🛠️ Deployment Instructions

### 1. Launch Containerized Environment
Verify your localized Docker server container instances are healthy:
```bash
docker compose up -d