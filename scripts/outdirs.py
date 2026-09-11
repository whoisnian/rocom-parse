"""生成脚本共用的输入/输出目录约定(环境变量,gen.sh 统一设置,单跑脚本时用默认值)。

  ROCOM_PARSED        解包根(unpack.sh 的产物),默认 ~/Downloads/rocom/parsed
  ROCOM_BUILD         生成物根,默认 ./build(不进仓库)
  ROCOM_GAMEDATA_OUT  names.json 与 img/ 的目录,默认 $ROCOM_BUILD/gamedata
  ROCOM_PBDESC_OUT    pcapdump 描述符目录,默认 $ROCOM_BUILD/pbdesc
  ROCOM_PB_OUT        protoc 生成的 Go 包目录,默认 $ROCOM_BUILD/pb
  ROCOM_PB_PKG        该 Go 包的 import 路径,默认 github.com/whoisnian/rocom-parse/build/pb
  ROCOM_PROFILE       capture(全量,默认)| minimal(只出宠物名称/头像/血脉/炫彩/标记的最小子集)

消费方把 *_OUT 指到自己 go:embed 的目录即可。
"""
import os

PARSED = os.environ.get("ROCOM_PARSED", os.path.expanduser("~/Downloads/rocom/parsed"))
BUILD = os.environ.get("ROCOM_BUILD", "build")
GAMEDATA_OUT = os.environ.get("ROCOM_GAMEDATA_OUT", os.path.join(BUILD, "gamedata"))
PBDESC_OUT = os.environ.get("ROCOM_PBDESC_OUT", os.path.join(BUILD, "pbdesc"))
PB_OUT = os.environ.get("ROCOM_PB_OUT", os.path.join(BUILD, "pb"))
PB_PKG = os.environ.get("ROCOM_PB_PKG", "github.com/whoisnian/rocom-parse/build/pb")
PROFILE = os.environ.get("ROCOM_PROFILE", "capture")
if PROFILE not in ("capture", "minimal"):
    raise SystemExit(f"ROCOM_PROFILE 只能是 capture 或 minimal,不是 {PROFILE!r}")

NAMES = os.path.join(GAMEDATA_OUT, "names.json")
IMG_OUT = os.path.join(GAMEDATA_OUT, "img")
