"""ComfyUI-freefield: Freefield's apps inside ComfyUI.

A sidebar tab lists the apps of Freefield (github.com/neuregex/freefield) by category. Opening one loads its
workflow into the canvas, with the lab's example already filled in; the tab also shows which model files and
node types this ComfyUI is missing for it, and downloads the models. No new nodes: every app is a plain ComfyUI
workflow, run with ComfyUI's own Run button.
"""
import logging

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}
WEB_DIRECTORY = "./web"

try:
    from .freefield_comfy import catalog, routes  # noqa: F401  (registers the /freefield/ routes)
    logging.info("[freefield] %d apps from %s@%s", len(catalog.apps()), catalog.load()["source"]["repo"],
                 catalog.load()["source"]["ref"])
except Exception as e:   # a broken catalog must not stop ComfyUI from starting
    logging.exception("[freefield] not loaded: %s", e)

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
