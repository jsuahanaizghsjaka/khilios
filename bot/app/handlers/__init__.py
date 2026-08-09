from aiogram import Router

from . import admin, billing, common, trial


def router() -> Router:
    """Порядок важен: common держит catch-all на «В меню» и должен идти последним."""
    root = Router()
    root.include_router(trial.router)
    root.include_router(billing.router)
    root.include_router(admin.router)
    root.include_router(common.router)
    return root
