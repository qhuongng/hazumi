from importlib import import_module
from pathlib import Path

from helpers.log import get_logger


LOGGER = get_logger(__name__)


def load_tool_functions() -> list:
	"""Load callable tools from files in this package.

	Convention: file name must match the tool function name.
	Example: tools/remember.py -> remember(...)
	"""

	tools_dir = Path(__file__).resolve().parent
	loaded_tools: list = []

	for file_path in sorted(tools_dir.glob("*.py")):
		module_name = file_path.stem
		if module_name.startswith("_") or module_name == "__init__":
			continue

		try:
			module = import_module(f"tools.{module_name}")
		except Exception as exc:
			LOGGER.exception("Tool load error (%s): %s", module_name, exc)
			continue

		tool_fn = getattr(module, module_name, None)
		if callable(tool_fn):
			loaded_tools.append(tool_fn)
		else:
			LOGGER.warning("Tool missing callable (%s): expected function `%s`", module_name, module_name)

	return loaded_tools
