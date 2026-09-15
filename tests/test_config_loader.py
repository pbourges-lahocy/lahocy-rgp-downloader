import sys
from pathlib import Path

import app.config.loader as loader_module
from app.config.loader import load_config

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "config.yaml"


def test_load_config_from_explicit_path():
    config = load_config(CONFIG_PATH)
    assert config.ign.base_url == "https://rgpdata.ign.fr/pub"
    assert 30 in config.ign.cadences


def test_app_root_uses_source_tree_when_not_frozen(monkeypatch):
    monkeypatch.setattr(loader_module, "_FROZEN", False)
    root = loader_module._app_root()
    assert (root / "config" / "config.yaml").exists()


def test_app_root_uses_meipass_when_frozen(monkeypatch, tmp_path):
    # _FROZEN est figé au premier import du module (reflet de sys.frozen au démarrage
    # réel d'un exécutable PyInstaller) : on patche donc directement cette constante
    # plutôt que sys.frozen, qui n'aurait plus d'effet après coup.
    monkeypatch.setattr(loader_module, "_FROZEN", True)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert loader_module._app_root() == tmp_path


def test_app_root_falls_back_to_executable_dir_when_frozen_without_meipass(monkeypatch, tmp_path):
    fake_exe = tmp_path / "LahocyRGPDownloader.exe"
    monkeypatch.setattr(loader_module, "_FROZEN", True)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_exe), raising=False)
    assert loader_module._app_root() == tmp_path


def test_default_cache_root_uses_local_app_data_when_frozen(monkeypatch, tmp_path):
    monkeypatch.setattr(loader_module, "_FROZEN", True)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert loader_module._default_cache_root() == tmp_path / "LahocyRGPDownloader"


def test_default_cache_root_uses_project_root_when_not_frozen(monkeypatch):
    monkeypatch.setattr(loader_module, "_FROZEN", False)
    assert loader_module._default_cache_root() == loader_module._PROJECT_ROOT


def test_cache_dir_resolves_relative_directory_against_default_root(monkeypatch, tmp_path):
    monkeypatch.setattr(loader_module, "_FROZEN", True)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    config = load_config(CONFIG_PATH)
    assert config.cache_dir == tmp_path / "LahocyRGPDownloader" / config.cache.directory
