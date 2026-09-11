// Package pbdesc 提供 opcode -> protobuf 消息类型的运行时反射能力,供 pcapdump 精确解码。
//
// 数据是 scripts/gen_pbdesc.py 从游戏描述符 all.pb + ProtoCMD.lua 精简出的生成物,
// 不进仓库、从目录加载(默认 build/pbdesc,见 DefaultDir):
//   - proto.desc.gz: FileDescriptorSet(仅保留 opcode 可达的消息/枚举,gzip)
//   - opmsg.json:    opcode -> 消息全名(如 786 -> .Next.ZoneGetAllHatchStatusRsp)
//   - opname.json:   opcode -> ZoneSvrCmd 枚举名(如 258 -> ZONE_LOGIN_RSP),含未映射消息的 opcode
//
// 这里用 dynamicpb 动态解析全部协议消息,只用于调试转储;线上解析路径(rocom-capture 的
// internal/pb)是 protoc 生成的静态结构体,与本包互不依赖。
package pbdesc

import (
	"compress/gzip"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strconv"

	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/reflect/protodesc"
	"google.golang.org/protobuf/reflect/protoreflect"
	"google.golang.org/protobuf/reflect/protoregistry"
	"google.golang.org/protobuf/types/descriptorpb"
	"google.golang.org/protobuf/types/dynamicpb"
)

// DefaultDir 返回生成物目录:环境变量 ROCOM_BUILD(默认 ./build)下的 pbdesc/。
func DefaultDir() string {
	root := os.Getenv("ROCOM_BUILD")
	if root == "" {
		root = "build"
	}
	return filepath.Join(root, "pbdesc")
}

// DB 是加载好的描述符集与 opcode 映射。
type DB struct {
	files  *protoregistry.Files
	opMsg  map[uint16]string
	opName map[uint16]string
}

// Load 从 dir 加载描述符与映射;dir 为空取 DefaultDir。
func Load(dir string) (*DB, error) {
	if dir == "" {
		dir = DefaultDir()
	}
	f, err := os.Open(filepath.Join(dir, "proto.desc.gz"))
	if err != nil {
		return nil, fmt.Errorf("pbdesc: %w(先跑 scripts/gen.sh 生成)", err)
	}
	defer f.Close()
	zr, err := gzip.NewReader(f)
	if err != nil {
		return nil, err
	}
	raw, err := io.ReadAll(zr)
	if err != nil {
		return nil, err
	}
	var fds descriptorpb.FileDescriptorSet
	if err := proto.Unmarshal(raw, &fds); err != nil {
		return nil, err
	}
	files, err := protodesc.NewFiles(&fds)
	if err != nil {
		return nil, err
	}
	opMsg, err := loadOpMap(filepath.Join(dir, "opmsg.json"))
	if err != nil {
		return nil, err
	}
	opName, err := loadOpMap(filepath.Join(dir, "opname.json"))
	if err != nil {
		return nil, err
	}
	return &DB{files: files, opMsg: opMsg, opName: opName}, nil
}

func loadOpMap(path string) (map[uint16]string, error) {
	blob, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("pbdesc: %w", err)
	}
	var m map[string]string
	if err := json.Unmarshal(blob, &m); err != nil {
		return nil, fmt.Errorf("pbdesc: %s: %w", path, err)
	}
	out := make(map[uint16]string, len(m))
	for k, v := range m {
		if op, err := strconv.ParseUint(k, 10, 16); err == nil {
			out[uint16(op)] = v
		}
	}
	return out, nil
}

// MessageName 返回 opcode 对应的消息全名(带前导点),未知返回空串。
func (db *DB) MessageName(op uint16) string { return db.opMsg[op] }

// OpcodeName 返回 opcode 的 ZoneSvrCmd 枚举名,未知返回空串。
func (db *DB) OpcodeName(op uint16) string { return db.opName[op] }

// OpcodeNames 返回 opcode -> 枚举名 全表(调用方只读)。
func (db *DB) OpcodeNames() map[uint16]string { return db.opName }

// Find 按消息全名(可省略前导点)查描述符。
func (db *DB) Find(name string) (protoreflect.MessageDescriptor, error) {
	if name == "" {
		return nil, fmt.Errorf("pbdesc: 消息名为空")
	}
	if name[0] == '.' {
		name = name[1:]
	}
	d, err := db.files.FindDescriptorByName(protoreflect.FullName(name))
	if err != nil {
		return nil, err
	}
	md, ok := d.(protoreflect.MessageDescriptor)
	if !ok {
		return nil, fmt.Errorf("pbdesc: %s 不是消息类型", name)
	}
	return md, nil
}

// FindOp 按 opcode 查消息描述符,未映射或查不到返回 nil。
func (db *DB) FindOp(op uint16) protoreflect.MessageDescriptor {
	md, err := db.Find(db.opMsg[op])
	if err != nil {
		return nil
	}
	return md
}

// New 按描述符创建可解码的动态消息。
func New(md protoreflect.MessageDescriptor) *dynamicpb.Message { return dynamicpb.NewMessage(md) }
