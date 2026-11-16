from app.config import DATABASE_PATH, PROJECT_ROOT


def test_project_paths_are_defined():
    assert PROJECT_ROOT.exists()
    assert DATABASE_PATH.name == "mobilestore.db"


def test_main_window_can_be_imported():
    from app.ui.main_window import MainWindow
    assert MainWindow is not None
