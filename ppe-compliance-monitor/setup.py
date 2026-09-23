from setuptools import setup, find_packages

setup(
    name="ppe-compliance-monitor",
    version="2.0.0",
    description="Real-Time Industrial PPE Compliance Monitoring — Django Edition (YOLOv10 + ByteTrack)",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    author="Kalam",
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        "Django>=4.2.0",
        "torch>=2.0.0",
        "torchvision>=0.15.0",
        "ultralytics>=8.0.0",
        "opencv-python>=4.7.0",
        "plotly>=5.15.0",
        "pandas>=2.0.0",
        "numpy>=1.24.0",
        "Pillow>=10.0.0",
        "supervision>=0.14.0",
        "filterpy>=1.4.5",
        "scipy>=1.10.0",
        "seaborn>=0.12.0",
    ],
    entry_points={
        "console_scripts": [
            "ppe-manage=manage:main",
        ]
    },
    python_requires=">=3.9",
    classifiers=[
        "Framework :: Django",
        "Programming Language :: Python :: 3",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
    ],
)
