"""Alerts subpackage — AlertChannel interface + fan-out dispatcher.

Per BUILD-PLAN.md §8:
  every configured channel fires, independently;
  a dead channel must never crash the loop.
"""

from .base import AlertChannel, dispatch  # noqa: F401
