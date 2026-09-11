// NrcUnpack:在 Linux 上从游戏 pak 全量解包(docs/data.md),供仓库生成脚本直接读取。
//
// 输出到 --out(默认 ~/Downloads/rocom/parsed),按虚拟路径镜像目录结构:
//   *.uasset/*.umap  → 同路径 .json(全部导出属性;Save Properties 等价)
//                      含纹理的包另出同路径 .png(Texture2D 解码)
//   *.uexp/*.ubulk/*.uptnl  随包体自动读取,不单独落盘
//   其余(.bytes/.non/.pb/.lua/.luac/.ini/...)  → 原样字节
//
// 依赖 CUE4Parse(内置 GAME_RocoKingdomWorld:自定义 AES 变体/Bin/luac 支持,无需 usmap)。
// AES 主密钥必传(unpack.sh 内置当前版本默认值)。

using System.Collections.Concurrent;
using System.Diagnostics;
using CUE4Parse.Compression;
using CUE4Parse.Encryption.Aes;
using CUE4Parse.FileProvider;
using CUE4Parse.FileProvider.Objects;
using CUE4Parse.FileProvider.Vfs;
using CUE4Parse.MappingsProvider.Usmap;
using CUE4Parse.UE4.Assets.Exports.Texture;
using CUE4Parse.UE4.Objects.Core.Misc;
using CUE4Parse.UE4.Versions;
using CUE4Parse.UE4.VirtualFileSystem;
using CUE4Parse_Conversion.Options;
using CUE4Parse_Conversion.Textures;
using Newtonsoft.Json;
using Serilog;
using Serilog.Events;

const string Usage = """
    用法: unpack.sh [选项]

    选项:
      --paks <path>     游戏 Paks 目录(递归扫描 *.pak/*.utoc)或安卓 .apk,
                        默认 ~/Downloads/rocom/Paks
      --aes <key>       AES 主密钥:64 位十六进制(可带 0x),或 @/path/to/key.txt
                        (unpack.sh 内置当前版本默认值,换密钥的版本才需传)
      --out <dir>       输出根目录,默认 ~/Downloads/rocom/parsed
      -j <n>            并行度,默认 CPU 核数
      --filter <prefix> 只导出虚拟路径以此前缀开头的文件(可重复,如 --filter NRC/Content/ScriptC)
      --exclude <prefix> 排除虚拟路径前缀(可重复,叠加在默认排除之上)
      --no-exclude      清空默认排除清单(真·全量导出;--exclude 仍生效)
      --usmap <path>    可选 .usmap 映射(当前版本无需)
      --force           全部重导(默认增量:产物存在且不比其来源 pak 旧才跳过,
                        故补丁包原地改过的同名文件会自动重导)
      --list [substr]   只列出将导出的虚拟路径(可选子串过滤)后退出

    默认排除(纯客户端运行时资源,下游脚本零引用;约占全量 74G/80G):
      NRC/Content/ArtRes/                三维美术(网格/材质/动画/特效)
      NRC/Content/Movies/                过场视频
      NRC/Content/NewRoco/WwiseAudio/    音频库
      NRC/Content/NewRoco/Modules/AI/    行为树/寻路
      NRC/Content/PVS/                   预计算可见性
      NRC/Content/PipelineCaches/        PSO 缓存
      NRC/Content/ShaderArchive-         着色器字节码
      Engine/                            UE 引擎自带资源
    """;

string[] defaultExcludes = [
    "NRC/Content/ArtRes/",
    "NRC/Content/Movies/",
    "NRC/Content/NewRoco/WwiseAudio/",
    "NRC/Content/NewRoco/Modules/AI/",
    "NRC/Content/PVS/",
    "NRC/Content/PipelineCaches/",
    "NRC/Content/ShaderArchive-",
    "Engine/",
];

var home = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
var paksPath = Path.Combine(home, "Downloads", "rocom", "Paks");
var outDir = Path.Combine(home, "Downloads", "rocom", "parsed");
string? aesArg = null, usmapPath = null, listFilter = null;
var parallelism = Environment.ProcessorCount;
var force = false; var listOnly = false; var noDefaultExcludes = false; var rawOnly = false;
var filters = new List<string>();
var extraExcludes = new List<string>();

for (var i = 0; i < args.Length; i++)
{
    switch (args[i])
    {
        case "--paks": paksPath = Next(ref i); break;
        case "--aes": aesArg = Next(ref i); break;
        case "--aes-file": aesArg = "@" + Next(ref i); break;
        case "--out": outDir = Path.GetFullPath(Next(ref i)); break;
        case "-j": parallelism = int.Parse(Next(ref i)); break;
        case "--filter": filters.Add(Next(ref i).TrimStart('/')); break;
        case "--exclude": extraExcludes.Add(Next(ref i).TrimStart('/')); break;
        case "--no-exclude": noDefaultExcludes = true; break;
        case "--raw": rawOnly = true; break;
        case "--usmap": usmapPath = Next(ref i); break;
        case "--force": force = true; break;
        case "--list":
            listOnly = true;
            if (i + 1 < args.Length && !args[i + 1].StartsWith("--")) listFilter = args[++i];
            break;
        case "-h" or "--help": Console.WriteLine(Usage); return 0;
        default: return Fail($"未知参数: {args[i]}\n{Usage}");
    }
}

if (aesArg is null) return Fail($"缺少 --aes\n{Usage}");

var aesKey = aesArg.StartsWith('@') ? File.ReadAllText(aesArg[1..]).Trim() : aesArg;
aesKey = string.Concat(aesKey.Where(c => !char.IsWhiteSpace(c)));
var aesHex = aesKey.StartsWith("0x", StringComparison.OrdinalIgnoreCase) ? aesKey[2..] : aesKey;
if (aesHex.Length != 64 || !aesHex.All(Uri.IsHexDigit))
    return Fail($"AES 密钥须为 64 位十六进制,拿到 {aesHex.Length} 位");

Log.Logger = new LoggerConfiguration().MinimumLevel.Is(LogEventLevel.Warning).WriteTo.Console().CreateLogger();
// Detex/oodle 原生库是 Windows dll;托管解码器(AssetRipper)全平台可用,PC 端 BC/DXT 与安卓 ASTC 都覆盖
TextureDecoder.UseAssetRipperTextureDecoder = true;

// oodle/zlib-ng 原生解压库:缺则自动下载到 ~/.cache/nrc-unpack(pak 未用到时失败也不致命)
var cacheDir = Path.Combine(home, ".cache", "nrc-unpack");
Directory.CreateDirectory(cacheDir);
try { OodleHelper.Initialize(Path.Combine(cacheDir, OodleHelper.OodleFileName)); }
catch (Exception e) { Console.Error.WriteLine($"[warn] Oodle 初始化失败(若 pak 未用 oodle 压缩可忽略): {e.Message}"); }
try { ZlibHelper.Initialize(Path.Combine(cacheDir, ZlibHelper.DllName)); }
catch (Exception e) { Console.Error.WriteLine($"[warn] zlib-ng 初始化失败(若 pak 未用 zlib 压缩可忽略): {e.Message}"); }

var version = new VersionContainer(EGame.GAME_RocoKingdomWorld);
AbstractVfsFileProvider provider;
if (File.Exists(paksPath) && paksPath.EndsWith(".apk", StringComparison.OrdinalIgnoreCase))
    provider = new ApkFileProvider(paksPath, versions: version, pathComparer: StringComparer.OrdinalIgnoreCase);
else if (Directory.Exists(paksPath))
    provider = new DefaultFileProvider(paksPath, SearchOption.AllDirectories, version, StringComparer.OrdinalIgnoreCase);
else
    return Fail($"--paks 路径不存在: {paksPath}");

if (usmapPath is not null)
    provider.MappingsContainer = new FileUsmapTypeMappingsProvider(usmapPath);

var sw = Stopwatch.StartNew();
provider.Initialize();
provider.SubmitKey(new FGuid(), new FAesKey(aesHex));
if (provider.Files.Count == 0)
    return Fail("挂载后没有任何文件:检查 --paks 目录是否含 pak、AES 密钥是否正确");
Console.WriteLine($"挂载 {provider.MountedVfs.Count} 个包,{provider.Files.Count} 个文件({sw.ElapsedMilliseconds}ms)");

// ── 扫描虚拟文件系统,生成任务 ─────────────────────────────────────
// Files.Values 枚举所有已挂载 pak 的索引:补丁包(_P)与基础包的同名文件都会出现,
// 须按路径去重,并经 Files[path] 索引器(按 readOrder 降序)取补丁优先的胜者。
// 输出路径 = 完整虚拟路径(如 NewRocoGame/Content/...),不同 mount 间天然无冲突。
var jobs = new List<(GameFile File, Kind Kind, string OutPath)>();
var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
var srcMtimeCache = new ConcurrentDictionary<string, DateTime>();
var skipped = 0;
var excludes = (noDefaultExcludes ? [] : defaultExcludes.AsEnumerable()).Concat(extraExcludes).ToArray();
foreach (var candidate in provider.Files.Values)
{
    var rel = candidate.Path.TrimStart('/');
    if (filters.Count > 0 && !filters.Any(f => rel.StartsWith(f, StringComparison.OrdinalIgnoreCase))) continue;
    if (excludes.Any(x => rel.StartsWith(x, StringComparison.OrdinalIgnoreCase))) continue;
    var ext = Path.GetExtension(rel).ToLowerInvariant();
    // --raw:包也按原始字节导,.uexp/.ubulk 各自成文件。用来看 CUE4Parse **不解**的那些段
    // ——比如材质 cooked resource 里的 shader map SHA1(属性表里没有,要拿原始字节去
    // shader library 的 ShaderMapHashes 里比对,见 scripts/shaderdump.py)。
    if (!rawOnly && ext is ".uexp" or ".ubulk" or ".uptnl") continue; // 随 .uasset 包体自动读取
    if (!seen.Add(candidate.Path)) continue;
    var file = provider.Files[candidate.Path];
    var kind = !rawOnly && ext is ".uasset" or ".umap" ? Kind.Package : Kind.Raw;
    var outPath = Path.Combine(outDir, kind == Kind.Package ? Path.ChangeExtension(rel, ".json") : rel);
    // 增量跳过:产物存在 **且** 不比其来源 pak 旧。只看存在与否是不够的——小版本更新的补丁包
    // (_N_P)大多是原地改同名文件(如 PETBASE_CONF.bytes / all.pb),产物路径不变,
    // 纯存在性判断会把这些改动全部静默跳过,解包结果停留在旧版本。
    // 包任务先写 .png 后写 .json,故 .json 的时间戳即整包完成时间,增量跳过安全。
    if (!force && IsUpToDate(outPath, file)) skipped++;
    else jobs.Add((file, kind, outPath));
}

if (listOnly)
{
    foreach (var j in jobs.Where(j => listFilter is null || j.File.Path.Contains(listFilter, StringComparison.OrdinalIgnoreCase)).OrderBy(j => j.File.Path))
        Console.WriteLine($"{j.Kind,-7} {j.File.Path}");
    Console.WriteLine($"共 {jobs.Count} 项(另有 {skipped} 项已存在将跳过)");
    return 0;
}

Console.WriteLine($"待导出 {jobs.Count} 项,已存在跳过 {skipped} 项,并行度 {parallelism}");
var done = 0;
var pngCount = 0;
var okByKind = new ConcurrentDictionary<string, int>();
var errors = new ConcurrentBag<string>();
sw.Restart();

Parallel.ForEach(jobs, new ParallelOptions { MaxDegreeOfParallelism = parallelism }, job =>
{
    try
    {
        Directory.CreateDirectory(Path.GetDirectoryName(job.OutPath)!);
        switch (job.Kind)
        {
            case Kind.Raw:
                File.WriteAllBytes(job.OutPath, job.File.Read());
                break;
            case Kind.Package:
                var exports = provider.LoadPackage(job.File).GetExports().ToList();
                foreach (var (tex, n) in exports.OfType<UTexture>().Select((t, n) => (t, n)))
                {
                    // 纹理解码失败(RenderTarget/视频纹理等无像素数据)只记录,属性 json 照写
                    try
                    {
                        var decoded = tex.Decode() ?? throw new InvalidOperationException($"纹理解码失败({tex.Format})");
                        // 单纹理包(常态)用包名;罕见多纹理包时后续项以导出名附加,避免互相覆盖
                        var path = Path.ChangeExtension(job.OutPath, n == 0 ? ".png" : $"{tex.Name}.png");
                        File.WriteAllBytes(path, decoded.Encode(ETextureFormat.Png, false, out _));
                        Interlocked.Increment(ref pngCount);
                    }
                    catch (Exception e)
                    {
                        errors.Add($"{job.File.Path}: {tex.Name}: {e.Message}");
                    }
                }
                File.WriteAllText(job.OutPath, JsonConvert.SerializeObject(exports, Formatting.Indented));
                break;
        }
        okByKind.AddOrUpdate(job.Kind.ToString().ToLowerInvariant(), 1, (_, v) => v + 1);
    }
    catch (Exception e)
    {
        errors.Add($"{job.File.Path}: {e.Message}");
    }
    var d = Interlocked.Increment(ref done);
    if (d % 2000 == 0) Console.WriteLine($"  ... {d}/{jobs.Count}({sw.Elapsed.TotalSeconds:F0}s)");
});

Console.WriteLine($"完成({sw.Elapsed.TotalSeconds:F1}s): " +
                  string.Join(", ", okByKind.OrderBy(kv => kv.Key).Select(kv => $"{kv.Key} {kv.Value}")) +
                  $",png {pngCount};跳过 {skipped},失败 {errors.Count}");
foreach (var err in errors.Take(20)) Console.Error.WriteLine($"[err] {err}");
if (errors.Count > 20) Console.Error.WriteLine($"[err] ... 共 {errors.Count} 个失败");
return errors.IsEmpty ? 0 : 2;

// 产物是否已是最新:存在且不早于其来源 pak 的修改时间。
// 来源取该文件的胜出 VFS(补丁包优先)对应的磁盘文件;取不到(如 apk 内嵌)则退回 --paks 本身。
bool IsUpToDate(string outPath, GameFile file)
{
    var outInfo = new FileInfo(outPath);
    if (!outInfo.Exists) return false;
    var srcPath = (file as VfsEntry)?.Vfs.Path;
    return outInfo.LastWriteTimeUtc >= SourceMtime(srcPath is not null && File.Exists(srcPath) ? srcPath : paksPath);
}

// pak 的 mtime 按路径缓存:每个 pak 几万个文件,不必反复 stat
DateTime SourceMtime(string path) => srcMtimeCache.GetOrAdd(path, static p =>
{
    try { return File.GetLastWriteTimeUtc(p); }
    catch { return DateTime.MaxValue; }   // 拿不到时间就当作「永远更新」,宁可重导也不漏导
});

string Next(ref int i)
{
    if (i + 1 >= args.Length) { Console.Error.WriteLine($"{args[i]} 缺少参数值\n{Usage}"); Environment.Exit(1); }
    return args[++i];
}

static int Fail(string msg)
{
    Console.Error.WriteLine(msg);
    return 1;
}

internal enum Kind { Raw, Package }
