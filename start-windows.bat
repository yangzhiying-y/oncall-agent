@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ====================================
echo 启动 知识库智能运维Agent 系统
echo ====================================
echo.

echo [1/8] 检查包管理器...
where uv >nul 2>&1
if errorlevel 1 (
    echo [信息] uv 未安装，将使用传统 pip 方式
    echo [提示] 安装 uv 可提升速度：pip install uv
    set USE_UV=0
) else (
    echo [成功] 检测到 uv 包管理器
    set USE_UV=1
)
echo.

echo [2/8] 配置 Python 版本...
if exist .python-version (
    set /p PYTHON_VERSION=<.python-version
    echo [信息] 当前配置版本: !PYTHON_VERSION!
    echo !PYTHON_VERSION! | findstr /C:"3.10" >nul
    if not errorlevel 1 (
        echo [警告] Python 3.10 不兼容，自动更新到 3.13...
        echo 3.13> .python-version
        echo [成功] 已更新到 Python 3.13
    )
) else (
    echo [信息] 创建 .python-version 文件...
    echo 3.13> .python-version
)
echo.

echo [3/8] 创建/同步虚拟环境...
if exist .venv\Scripts\python.exe (
    echo [信息] 虚拟环境已存在，检查更新...
    if "%USE_UV%"=="1" (
        uv sync 2>nul
        if errorlevel 1 (
            echo [警告] uv sync 失败，使用 pip 更新...
            .venv\Scripts\python.exe -m pip install -e . -q
        ) else (
            echo [成功] 使用 uv 同步完成
        )
    ) else (
        echo [信息] 使用 pip 更新依赖...
        .venv\Scripts\python.exe -m pip install -e . -q
    )
) else (
    echo [信息] 创建新的虚拟环境...
    if "%USE_UV%"=="1" (
        echo [信息] 尝试使用 uv sync 创建...
        uv sync 2>nul
        if not errorlevel 1 (
            echo [成功] 使用 uv 创建完成
            goto :venv_created
        )
        echo [警告] uv sync 失败，回退到传统方式...
    )
    echo [信息] 使用 python -m venv 创建...
    python -m venv .venv
    if errorlevel 1 (
        echo [错误] 虚拟环境创建失败
        echo [提示] 请确保已安装 Python 3.11+
        pause
        exit /b 1
    )
    echo [信息] 安装项目依赖（这可能需要几分钟）...
    .venv\Scripts\python.exe -m pip install --upgrade pip -q
    .venv\Scripts\python.exe -m pip install -e . -q
    if errorlevel 1 (
        echo [错误] 依赖安装失败
        pause
        exit /b 1
    )
    echo [成功] 虚拟环境创建完成
)

:venv_created
echo [成功] 虚拟环境就绪
echo.

set PYTHON_CMD=.venv\Scripts\python.exe

echo [4/8] 启动 Milvus 向量数据库...
docker ps --format "{{.Names}}" | findstr "milvus-standalone" >nul 2>&1
if not errorlevel 1 (
    echo [信息] Milvus 容器已在运行
) else (
    docker compose -f vector-database.yml up -d
    if errorlevel 1 (
        echo [错误] Docker 启动失败，请确保 Docker Desktop 已启动
        pause
        exit /b 1
    )
    echo [信息] 等待 Milvus 启动（10秒）...
    timeout /t 10 /nobreak >nul
)
echo [成功] Milvus 数据库就绪
echo.

echo [5/8] 启动 CLS MCP 服务...
start "CLS MCP Server" /min %PYTHON_CMD% mcp_servers\cls_server.py
timeout /t 2 /nobreak >nul
echo [成功] CLS MCP 服务已启动
echo.

echo [6/8] 启动 Monitor MCP 服务...
start "Monitor MCP Server" /min %PYTHON_CMD% mcp_servers\monitor_server.py
timeout /t 2 /nobreak >nul
echo [成功] Monitor MCP 服务已启动
echo.

echo [7/8] 启动 FastAPI 服务...
start "知识库智能运维Agent 系统 API" %PYTHON_CMD% -m uvicorn app.main:app --host 0.0.0.0 --port 9900
echo [信息] 等待服务启动（15秒）...
timeout /t 15 /nobreak >nul
echo.

echo.
echo [信息] 检查服务状态...
where curl >nul 2>&1
if errorlevel 1 (
    echo [信息] curl 未找到，使用 PowerShell 检查...
    powershell -Command "try { $r=Invoke-WebRequest -Uri http://localhost:9900/health -UseBasicParsing; exit 0 } catch { exit 1 }" >nul 2>&1
    if errorlevel 1 (
        echo [警告] 服务可能还未完全启动，请稍等片刻
        goto :skip_upload
    )
) else (
    curl -s http://localhost:9900/health >nul 2>&1
    if errorlevel 1 (
        echo [警告] 服务可能还未完全启动，请稍等片刻
        goto :skip_upload
    )
)
echo [成功] FastAPI 服务运行正常
echo.
echo [8/8] 知识库文档同步
choice /C YN /N /M "是否重新导入 aiops-docs 中的示例文档"
if errorlevel 2 (
    echo [信息] 已跳过示例文档导入（不会重复建立索引）
    goto :skip_upload
)
echo [信息] 正在导入示例文档到向量数据库...
for %%f in (aiops-docs\*.md) do (
    echo   上传: %%~nxf
    curl -s -X POST http://localhost:9900/api/upload -F "file=@%%f" >nul 2>&1
)
echo [成功] 文档上传完成
:skip_upload

echo.
echo ====================================
echo 服务启动完成！
echo ====================================
echo Web 界面: http://localhost:9900
echo API 文档: http://localhost:9900/docs
echo.
echo 查看日志:
echo   - FastAPI: logs\app_*.log（Loguru 日志，按天轮转）
echo   - CLS MCP: type mcp_cls.log
echo   - Monitor: type mcp_monitor.log
echo 停止服务: stop-windows.bat
echo ====================================
pause
