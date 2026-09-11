package main

// 精确解码:按 opcode 查到真实消息类型(internal/pbdesc 内嵌的游戏描述符),用 dynamicpb 解出
// 带字段名/枚举名的结构树。相比通用 wire 解码,不会把嵌套切错,也不用人肉猜字段含义。
//
// AppBody 两端的边界靠试:头部可能还有 c2s 子头(gcp.AppBody 只剥了固定前缀),
// 尾部有 tsf4g 校验尾。以 "tsf4g" 为锚,在 [起始 0..16] × [结束 tail-24..tail] 的候选里
// 取「无未知字段 + 消费字节最多 + 回序列化长度一致」者。
//
// 注:回序列化只比长度不比字节 —— Go 按字段声明顺序编码,服务端按字段号顺序,
// 字段号与声明顺序不一致的消息(本协议里常见)字节序列会不同,但长度必然相同。

import (
	"fmt"
	"strings"
	"unicode/utf8"

	"github.com/whoisnian/rocom-parse/pbdesc"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/reflect/protoreflect"
)

const (
	maxStartProbe = 16 // 头部最多试探多少字节
	maxTailProbe  = 24 // tsf4g 标记之前最多回退多少字节
	// 实测的 proto 起始偏移:s2c 的 internal header 已由 gcp.AppBody 剥净;
	// c2s 还剩 6 字节子头(c0 50 00 00 00 XX)。仅作候选打分的偏好,解不出时照样全试。
	startHintS2C = 0
	startHintC2S = 6
)

type typedResult struct {
	msg     protoreflect.Message
	start   int  // 消息在 AppBody 中的起始偏移
	trailer int  // 尾部剩余字节数
	exact   bool // 回序列化长度与原字节一致(边界判定可信)
	hinted  bool // 起始偏移正好是该方向的常见值
}

// decodeTyped 用给定消息类型解 body,失败返回 nil。hint 是该方向常见的 proto 起始偏移
// (候选打平时优先它:短消息里头部字节常能凑出另一种同样合法的解法)。
func decodeTyped(md protoreflect.MessageDescriptor, body []byte, hint int) *typedResult {
	tail := indexOf(body, []byte("tsf4g"))
	ends := []int{}
	if tail >= 0 {
		for e := tail; e >= tail-maxTailProbe && e >= 0; e-- {
			ends = append(ends, e)
		}
	} else {
		ends = append(ends, len(body))
	}
	var best *typedResult
	for s := 0; s <= min(maxStartProbe, len(body)); s++ {
		for _, e := range ends {
			if e < s {
				continue
			}
			seg := body[s:e]
			m := pbdesc.New(md)
			if err := proto.Unmarshal(seg, m.Interface()); err != nil {
				continue
			}
			if len(m.GetUnknown()) > 0 { // 有未知字段说明边界或类型不对
				continue
			}
			out, err := proto.Marshal(m.Interface())
			exact := err == nil && len(out) == len(seg)
			cur := &typedResult{msg: m, start: s, trailer: len(body) - e, exact: exact, hinted: s == hint}
			if best == nil || better(cur, best, body) {
				best = cur
			}
		}
	}
	return best
}

// better 比较两个候选:空解码垫底(无字段的 REQ 才会落到它),
// 其次看回序列化长度是否一致,再看消费字节数,最后取起始更靠前者。
func better(a, b *typedResult, body []byte) bool {
	al, bl := len(body)-a.start-a.trailer, len(body)-b.start-b.trailer
	if (al == 0) != (bl == 0) {
		return bl == 0
	}
	if a.exact != b.exact {
		return a.exact
	}
	if al != bl {
		return al > bl
	}
	if a.hinted != b.hinted {
		return a.hinted
	}
	return a.start < b.start
}

// renderMsg 把动态消息渲染成 prototext 风格的缩进树(只列已置位的字段)。
func renderMsg(m protoreflect.Message, depth int, sb *strings.Builder) {
	ind := strings.Repeat("  ", depth)
	fields := m.Descriptor().Fields()
	for i := 0; i < fields.Len(); i++ {
		fd := fields.Get(i)
		if !m.Has(fd) {
			continue
		}
		v := m.Get(fd)
		switch {
		case fd.IsMap():
			v.Map().Range(func(k protoreflect.MapKey, mv protoreflect.Value) bool {
				fmt.Fprintf(sb, "%s%s[%s]%s", ind, fd.Name(), k.String(), sep(fd.MapValue()))
				renderValue(fd.MapValue(), mv, depth, sb)
				return true
			})
		case fd.IsList():
			l := v.List()
			for j := 0; j < l.Len(); j++ {
				fmt.Fprintf(sb, "%s%s%s", ind, fd.Name(), sep(fd))
				renderValue(fd, l.Get(j), depth, sb)
			}
		default:
			fmt.Fprintf(sb, "%s%s%s", ind, fd.Name(), sep(fd))
			renderValue(fd, v, depth, sb)
		}
	}
	if unk := m.GetUnknown(); len(unk) > 0 {
		fmt.Fprintf(sb, "%s# 未知字段(%dB):\n", ind, len(unk))
		f, _ := scanProto(unk)
		renderFields(f, depth+1, sb)
	}
}

// sep 是字段名与值之间的分隔:子消息用 prototext 的 `name {`,标量用 `name: v`。
func sep(fd protoreflect.FieldDescriptor) string {
	switch fd.Kind() {
	case protoreflect.MessageKind, protoreflect.GroupKind:
		return " "
	}
	return ": "
}

func renderValue(fd protoreflect.FieldDescriptor, v protoreflect.Value, depth int, sb *strings.Builder) {
	switch fd.Kind() {
	case protoreflect.MessageKind, protoreflect.GroupKind:
		sb.WriteString("{\n")
		renderMsg(v.Message(), depth+1, sb)
		fmt.Fprintf(sb, "%s}\n", strings.Repeat("  ", depth))
	case protoreflect.EnumKind:
		n := v.Enum()
		if ev := fd.Enum().Values().ByNumber(n); ev != nil {
			fmt.Fprintf(sb, "%s(%d)\n", ev.Name(), n)
		} else {
			fmt.Fprintf(sb, "%d\n", n)
		}
	case protoreflect.StringKind:
		fmt.Fprintf(sb, "%q\n", v.String())
	case protoreflect.BytesKind:
		b := v.Bytes()
		if utf8Text(b) {
			fmt.Fprintf(sb, "%q\n", string(b))
		} else {
			fmt.Fprintf(sb, "%s (%dB)\n", hexPreview(b, 64), len(b))
		}
	default:
		fmt.Fprintf(sb, "%s\n", v.String())
	}
}

// utf8Text 判断 bytes 字段是否是可读文本(玩家名/宠物名等常以 bytes 下发)。
func utf8Text(b []byte) bool {
	if len(b) == 0 || !utf8.Valid(b) {
		return false
	}
	for _, r := range string(b) {
		if r < 0x20 && r != '\n' && r != '\t' {
			return false
		}
	}
	return true
}
