#!/bin/bash

# 测试脚本

echo "=== 健康检查 ==="
curl -s http://localhost:3006/health | jq .

echo ""
echo "=== 分析示例项目 ==="
curl -s -X POST http://localhost:3006/analyze \
  -F "problem_description=Create a multi-channel forum api with create channel, write messages, and list messages features" \
  -F "code_zip=@/tmp/test-project.zip" | jq .
