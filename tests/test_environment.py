"""
环境验证脚本 - 检查Python环境和依赖是否正确安装

运行方式：
1. 在PyCharm中右键 → Run 'test_environment'
2. 或在Terminal中运行: python test_environment.py
"""

import sys
import subprocess


def check_python_version():
    """检查Python版本"""
    print("=" * 60)
    print("🐍 Python 环境检查")
    print("=" * 60)

    version = sys.version_info
    print(f"Python 版本: {version.major}.{version.minor}.{version.micro}")
    print(f"Python 路径: {sys.executable}")

    if version.major == 3 and version.minor >= 8:
        print("✅ Python 版本符合要求 (>= 3.8)")
        return True
    else:
        print("❌ Python 版本过低，需要 3.8 或更高版本")
        return False


def check_pip():
    """检查pip是否可用"""
    print("\n" + "=" * 60)
    print("📦 pip 检查")
    print("=" * 60)

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "--version"],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            print(f"✅ pip 可用: {result.stdout.strip()}")
            return True
        else:
            print("❌ pip 不可用")
            return False
    except Exception as e:
        print(f"❌ pip 检查失败: {e}")
        return False


def check_dependencies():
    """检查关键依赖是否已安装"""
    print("\n" + "=" * 60)
    print("📚 依赖检查")
    print("=" * 60)

    required_packages = {
        "fastapi": "FastAPI",
        "pydantic": "Pydantic",
        "pydantic_settings": "Pydantic Settings",
        "yaml": "PyYAML",
        "uvicorn": "Uvicorn",
        "structlog": "Structlog",
        "tenacity": "Tenacity",
    }

    installed = []
    missing = []

    for module_name, display_name in required_packages.items():
        try:
            __import__(module_name)
            print(f"  ✅ {display_name}")
            installed.append(display_name)
        except ImportError:
            print(f"  ❌ {display_name} - 未安装")
            missing.append(display_name)

    print(f"\n已安装: {len(installed)}/{len(required_packages)}")

    if missing:
        print(f"\n⚠️ 缺少以下依赖: {', '.join(missing)}")
        print("\n安装命令:")
        print("pip install -r requirements.txt")
        return False
    else:
        print("\n✅ 所有核心依赖已安装")
        return True


def check_project_modules():
    """检查项目内部模块是否可以导入"""
    print("\n" + "=" * 60)
    print("🔧 项目模块检查")
    print("=" * 60)

    modules = [
        ("app.infrastructure.config", "配置模块"),
        ("app.infrastructure.logger", "日志模块"),
        ("app.infrastructure.error_handler", "错误处理模块"),
        ("app.infrastructure.circuit_breaker", "熔断器模块"),
        ("app.api.schemas", "数据模型模块"),
    ]

    success_count = 0

    for module_path, display_name in modules:
        try:
            __import__(module_path)
            print(f"  ✅ {display_name}")
            success_count += 1
        except ImportError as e:
            print(f"  ❌ {display_name}: {e}")
        except Exception as e:
            print(f"  ⚠️ {display_name}: {type(e).__name__} - {e}")

    if success_count == len(modules):
        print("\n✅ 所有项目模块正常")
        return True
    else:
        print(f"\n⚠️ {len(modules) - success_count} 个模块有问题")
        return False


def main():
    """主测试流程"""
    print("\n" + "🚀" * 20)
    print("AI Interview Agent - 环境验证")
    print("🚀" * 20 + "\n")

    results = {
        "Python版本": check_python_version(),
        "pip工具": check_pip(),
        "核心依赖": check_dependencies(),
        "项目模块": check_project_modules(),
    }

    print("\n" + "=" * 60)
    print("📊 检查结果汇总")
    print("=" * 60)

    for name, passed in results.items():
        status = "✅ 通过" if passed else "❌ 失败"
        print(f"  {name}: {status}")

    all_passed = all(results.values())

    print("\n" + "=" * 60)
    if all_passed:
        print("🎉 恭喜！所有检查通过，环境配置完成！")
        print("可以开始开发 Step 4 了！")
    else:
        print("⚠️ 部分检查未通过，请按照上面的提示修复")
        print("\n常见解决方案：")
        print("1. 如果缺少依赖: pip install -r requirements.txt")
        print("2. 如果Python版本低: 安装 Python 3.8+")
        print("3. 如果模块导入失败: 检查 PYTHONPATH 或在项目根目录运行")
    print("=" * 60)

    return all_passed


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
