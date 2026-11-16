# benchmarks/

用于测量 Facet Proof 资源边界的脚本与原始数据。生产代码未修改。

## 快速开始

```sh
export TMPDIR=/dev/shm   # 根文件系统空间不足时（本项目实测曾耗尽）
python3 benchmarks/sweep.py
python3 benchmarks/tile_livelock.py
python3 benchmarks/summarize.py
```

完整报告见 `REPORT.md`。

## 脚本

| 文件 | 作用 | 典型耗时 |
|---|---|---|
| `lib.py` | 共享驱动：确定性几何、Harness、RSS 采样 | — |
| `case_runner.py` | 单用例独立进程，`ru_maxrss` 峰值内存 | 0.1–45 s/例 |
| `sweep.py` | 覆盖面积 / 面数 / 采样三维度扫描 → `results/sweep.jsonl` | 约 4 分钟 |
| `phase_profile.py` | 规划、分块、下采样+PNG、写盘的分段计时 | 10–35 s/例 |
| `bbox_correlation.py` | 墙钟对“包围盒像素和”的最小二乘拟合 | 约 1 分钟 |
| `cancel_probe.py` | 排队/分块/收尾三阶段取消后的产物 | 约 30 s |
| `cancel_sweep.py` | 取消延迟扫描与确认延迟 | 约 2 分钟 |
| `http_probe.py` | 真实 HTTP 服务下的取消与终态后审阅 | 约 20 s |
| `recovery_probe.py` | SIGKILL、租约过期、重启后的块复用 | 约 1 分钟 |
| `concurrency_probe.py` | 多进程 worker 争抢、CAS 字节增长 | 约 1 分钟 |
| `thread_concurrency.py` | 两个最大任务同进程并发的峰值内存 | 约 30 s |
| `memory_limit.py` | RLIMIT_AS 下的 `resource_failure` 与恢复 | 约 2 分钟 |
| `unrenderable_recovery.py` | 不可完成请求的取消、额度归还、缩小重提 | 约 3 分钟 |
| `tile_livelock.py` | **单块超过 45 秒导致永不成功**（核心发现） | 约 4 分钟 |
| `supplementary.py` | span 实验、40000 小包围盒面、规划器内存 | 约 40 s |
| `summarize.py` | 从原始 JSON 生成 Markdown 表格 | <1 s |

## 数据

- `results/*.json` / `*.jsonl`：原始测量，含 spec 与逐项观测。
- `results/tables.md`：`summarize.py` 生成的表格。
- `results/livelock_30k.json`：30000 面同配置的一次性运行，仅用于趋势，无对应脚本。
- 被并发干扰的批次已删除，不保留。

## 已知限制

- 数据来自单机单次采集，墙钟波动 ±5–10%；距 45 秒预算 10% 内的结果不作判据。
- 峰值内存用 `ru_maxrss`，采集线程自身开销 <1% CPU。
- 所有几何为合成的宽三角扇或均匀网格，不代表真实模型分布。
