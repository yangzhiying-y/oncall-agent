@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ====================================
echo 停止 知识库智能运维Agent 系统
echo ====================================
echo.

REM 辅助函数：根据端口杀掉进程
call :KillByPort 9900 "FastAPI 服务"
echo.
call :KillByPort 8003 "CLS MCP 服务"
echo.
call :KillByPort 8004 "Monitor MCP 服务"
echo.

REM 停止 Docker 容器
echo [4/4] 停止 Milvus 容器...
docker ps --format "{{.Names}}" 2>nul | findstr "milvus" >nul 2>&1
if not errorlevel 1 (
    docker compose -f vector-database.yml down 2>nul
    if errorlevel 1 (
        REM 兼容旧版 docker-compose
        docker-compose -f vector-database.yml down 2>nul
        if errorlevel 1 (
            echo [错误] Docker 容器停止失败
        ) else (
            echo [成功] Milvus 容器已停止
        )
    ) else (
        echo [成功] Milvus 容器已停止
    )
) else (
    echo [信息] Milvus 容器未运行
)
echo.

echo ====================================
echo 所有服务已停止！
echo ====================================
echo.
echo 提示:
echo   - 如需完全清理 Docker 数据卷，运行:
echo     docker compose -f vector-database.yml down -v
echo.
pause
exit /b 0

:KillByPort
REM %1 = 端口号, %2 = 服务名称
echo [信息] 停止 %~2 (端口 %~1)...
set "pid="
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%~1.*LISTENING" 2^>nul') do (
    set "pid=%%a"
    goto :found_pid
)
goto :not_found

:found_pid
if "!pid!"=="" goto :not_found
echo [信息] 找到进程 PID: !pid!，正在终止...
taskkill /F /PID !pid! >nul 2>&1
if errorlevel 1 (
    echo [错误] 无法终止进程 !pid!
) else (
    echo [成功] %~2 已停止 (PID: !pid!)
)
goto :eof

:not_found
echo [信息] %~2 未运行或已停止
goto :eof
