import os


def powershell_environment():
    environment = dict(os.environ)
    # Windows PowerShell precisa resolver seus próprios módulos ao sair de um host PowerShell 7.
    environment.pop("PSModulePath", None)
    return environment
