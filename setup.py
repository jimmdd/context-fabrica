from setuptools import setup


setup(
    name="context-fabrica",
    version="0.1.0",
    description="Hybrid graph + semantic memory engine for domain-specific work agents",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    python_requires=">=3.9",
    author="context-fabrica contributors",
    license="MIT",
    package_dir={"": "src"},
    packages=[
        "context_fabrica",
        "context_fabrica.storage",
    ],
    entry_points={
        "console_scripts": [
            "context-fabrica=context_fabrica.cli:main",
            "context-fabrica-demo=context_fabrica.demo_cli:main",
            "context-fabrica-bootstrap=context_fabrica.bootstrap_cli:main",
            "context-fabrica-doctor=context_fabrica.doctor_cli:main",
            "context-fabrica-projector=context_fabrica.projector_cli:main",
            "context-fabrica-project-memory=context_fabrica.project_memory_cli:main",
        ]
    },
)
