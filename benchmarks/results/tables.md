## Sweep

| axis | geometry | source faces | request | wall s | peak RSS MB | Δ RSS MB | state |
|---|---|---|---|---|---|---|---|
| coverage | fan | 48 | 64x64 s1 | 0.088 | 18.4 | 0.6 | succeeded |
| coverage | fan | 48 | 128x128 s1 | 0.248 | 19.2 | 1.3 | succeeded |
| coverage | fan | 48 | 256x256 s1 | 0.864 | 22.0 | 4.2 | succeeded |
| coverage | fan | 48 | 384x384 s1 | 1.891 | 26.6 | 8.8 | succeeded |
| coverage | fan | 48 | 512x512 s1 | 4.487 | 33.5 | 15.7 | succeeded |
| coverage-small | fan | 48 | 256x256 s1 | 0.714 | 22.0 | 4.1 | succeeded |
| coverage-small | fan | 48 | 512x512 s1 | 1.364 | 33.5 | 15.7 | succeeded |
| faces-fan | fan | 8 | 256x256 s1 | 0.521 | 21.9 | 4.1 | succeeded |
| faces-fan | fan | 48 | 256x256 s1 | 0.879 | 22.0 | 4.2 | succeeded |
| faces-fan | fan | 256 | 256x256 s1 | 2.977 | 22.7 | 4.5 | succeeded |
| faces-fan | fan | 1000 | 256x256 s1 | 9.898 | 25.6 | 6.3 | succeeded |
| faces-fan | fan | 2000 | 256x256 s1 | 19.164 | 28.6 | 7.5 | succeeded |
| faces-fan | fan | 4000 | 256x256 s1 | 36.587 | 32.9 | 8.3 | succeeded |
| faces-fan | fan | 8000 | 256x256 s1 | 45.018 | 45.4 | 14.0 | failed/render_timeout |
| faces-grid | grid | 100 | 256x256 s1 | 0.491 | 22.0 | 4.1 | succeeded |
| faces-grid | grid | 1000 | 256x256 s1 | 0.612 | 25.2 | 6.3 | succeeded |
| faces-grid | grid | 5000 | 256x256 s1 | 0.806 | 34.4 | 10.3 | succeeded |
| faces-grid | grid | 19602 | 256x256 s1 | 1.672 | 76.5 | 34.3 | succeeded |
| faces-multi | grid | 5000 | 256x256 s1 | 1.462 | 31.6 | 10.3 | succeeded |
| faces-multi | grid | 20000 | 256x256 s1 | 4.441 | 62.4 | 33.5 | succeeded |
| samples | grid | 5000 | 256x256 s1 | 0.816 | 34.4 | 10.3 | succeeded |
| samples | grid | 5000 | 256x256 s2 | 1.981 | 39.0 | 14.9 | succeeded |
| max-legal | grid | 19602 | 512x512 s2 | 12.987 | 97.1 | 54.9 | succeeded |
| max-legal-fan | fan | 8000 | 512x512 s2 | 45.016 | 45.3 | 13.9 | failed/render_timeout |

## Cancel timing

| delay s | state before | tiles before | HTTP | accept ms | worker terminal after cancel s | worker result | plate | bundle |
|---|---|---|---|---|---|---|---|---|
| 0.0 | running | 0/0 | running | 14 | 0.025 | cancelled | no | no |
| 0.2 | succeeded | 1/1 | 409 | 0 (rejected:state) | -0.136 | succeeded | yes | yes |
| 0.5 | succeeded | 1/1 | 409 | 1 (rejected:state) | -0.446 | succeeded | yes | yes |
| 0.8 | succeeded | 1/1 | 409 | 0 (rejected:state) | -0.742 | succeeded | yes | yes |
| 1.2 | succeeded | 1/1 | 409 | 0 (rejected:state) | -1.136 | succeeded | yes | yes |
| 0.5 | running | 0/16 | running | 7 | 0.025 | cancelled | no | no |
| 1.5 | running | 1/16 | running | 63 | 0.164 | cancelled | no | no |
| 3.0 | running | 1/16 | running | 52 | 0.122 | cancelled | no | no |
| 5.0 | running | 2/16 | running | 6 | 0.025 | cancelled | no | no |
| 10.0 | running | 238/256 | running | 48 | 0.113 | cancelled | no | no |
| 11.5 | running | 254/256 | running | 3 | 0.016 | cancelled | no | no |
| 12.5 | running | 256/256 | running | 104 | 0.621 | cancelled | no | no |

## Phases

| geometry | faces | request | plan s | tiles s | downsample+PNG s | blob s | total s |
|---|---|---|---|---|---|---|---|
| grid | 19602 | 512x512 s2 | 0.494 | 9.406 | 1.006 | 0.038 | 10.944 |
| fan | 4000 | 256x256 s1 | 0.106 | 34.516 | 0.195 | 0.048 | 34.865 |
| fan | 48 | 512x512 s2 | 0.001 | 11.001 | 0.973 | 0.042 | 12.018 |

## Variance

| case | wall min/mean/max s | peak RSS min/mean/max MB |
|---|---|---|
| grid 19602 faces 512x512 s2 | 12.29 / 13.47 / 14.99 | 97.1 / 97.1 / 97.1 |
| fan 1000 faces 256x256 s1 | 9.67 / 10.08 / 10.63 | 25.3 / 25.5 / 25.6 |
| fan 48 faces 512x512 s1 | 3.41 / 3.62 / 3.95 | 33.4 / 33.4 / 33.5 |

## Memory scaling

| high-sample pixels | wall s | peak RSS MB | Δ RSS MB |
|---|---|---|---|
| 4096 | 0.102 | 18.3 | 0.5 |
| 16384 | 0.284 | 19.1 | 1.3 |
| 65536 | 0.915 | 22.0 | 4.1 |
| 262144 | 3.721 | 33.4 | 15.6 |
| 262144 | 3.441 | 26.7 | 8.9 |
| 1048576 | 13.554 | 52.4 | 34.6 |
