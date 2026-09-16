; Korean text renderer for Downtown Nekketsu Baseball Monogatari (SFC).
; Assembled with ca65 into bank $B1 ($31 slow). See build.py for the patch sites.
;
; The original dialogue routine ($10:E9D5) draws one 8x8 font tile per byte into
; the window tilemap. We keep its control flow (per-character wait, variable
; substitution, window handling) and replace the character path: glyphs are
; 16px-high proportional bitmaps drawn into a WRAM tile buffer that the NMI hook
; DMAs into a cache area of VRAM. The window tilemap is pre-filled with the cache
; tile numbers when a message starts. Words are wrapped at run time so the same
; string works in the narrow menu window and the full-width dialogue window.

.p816
.smart +

SCRIPT_BANK     = $B0
WIDTHS          = $B19800       ; 1 byte per glyph index
GLYPH_BANK0     = $B2           ; 1024 glyphs (32 bytes each) per bank

ORIG_WAIT       = $10EA25       ; per-character delay, then falls into the loop head
ORIG_END        = $10EAB5       ; end of message
ORIG_VAR        = $10EA8C       ; F0 xx handler (reads xx, dispatches)
ORIG_NEST_WAIT  = $10EBF1       ; nested string: delay, then loop head
ORIG_NEST_END   = $10EC60       ; nested string finished
ORIG_NMI        = $80F6B1
TILEMAP_PUT     = $91ADA2       ; X=col Y=row A=tile word -> current window buffer
SFX_PLAY        = $80FAB2
SFX_FLAG        = $7E6FE7
WINDOW_SEL      = $7E2F2B
BG34NBA_SHADOW  = $7E005C       ; copied to $210C by the game

; task direct-page frame of the dialogue routine
T_X     = $02                   ; tile column (kept in step for number printing)
T_Y     = $04                   ; tile row of the current line
T_X0    = $06                   ; first column
T_PTR   = $0E                   ; main string pointer
T_WIN   = $10                   ; window handle
T_NPTR  = $12                   ; nested string pointer

; renderer state (bank $7E, absolute long)
ST      = $7E1480
PEN_X   = ST+0                  ; pixel position from the first column
LINE    = ST+2                  ; 0 or 1
XCOL0   = ST+4
MAX_PX  = ST+6
FLAG    = ST+8                  ; = FLAG_MAGIC when the NMI must upload
VRAMW   = ST+10                 ; VRAM word address of the cache
CTILE   = ST+12                 ; first cache tile number
NCOLS   = ST+14
C_COL   = ST+16
C_ROW   = ST+18
RANGE   = ST+20                 ; low byte: first dirty column, high byte: last
N_TMP   = ST+22                 ; NMI-only scratch
FLAG_MAGIC = $A55A
RANGE_EMPTY = $00FF

BUF       = $7E9000             ; WRAM $7E:9000-$9BFF has no references in the game code
BUF_COLS  = 33                  ; 31 visible + 2 spare for the last glyph
BUF_SIZE  = BUF_COLS*64
SPACE_W   = 6
MAX_LINES = 2
OVERFLOW_X = $4000              ; pen position that suppresses further drawing

; ---- in-game commentary window (bank $04 renderer) ---------------------------
GAME_MAIN_CONT  = $04CC44       ; message finished
GAME_VAR        = $04CC90       ; F0 xx handler (nested strings / numbers)
GAME_NEST_END   = $04CC24       ; nested string finished
GAME_WAIT       = $04CF59       ; one frame per character, back to the task loop
GAME_MAIN_HEAD  = $04CC37
VRAM_QUEUE      = $80F0FD       ; X=source ($7E), Y=VRAM word, A=bytes; carry set = queue full
TASK_WAIT       = $80EC8A
G_PTR           = $7E6933       ; main string pointer (script bank)
G_NPTR          = $7E6936       ; nested string pointer
G_CELL          = $7E691D       ; VRAM word address of the next cell
GST     = $7E14E0
G_BASE  = GST+0                 ; VRAM word address of the first cell of line 0
MODE    = GST+2                 ; 0 = dialogue window, 1 = in-game commentary
G_DROP  = GST+4                 ; nonzero: no room left, swallow the rest of the message
G_COL   = GST+6                 ; cells used on the current line
D_NEXT  = GST+8                 ; next dynamic 8x8 slot to reuse
D_TMP   = GST+10
D_ID    = GST+12
GAME_COLS = 22
GAME_LINE2 = $3F                ; second line starts at base + $3F (as the original)
HUD_NAME_CONT = $0EF805         ; after the name cells are built
HUD_CELLS = 5                   ; cells queued per name
G_CELLWORD = $7E6921            ; the original's cell word for the VRAM queue
G_BLANK    = $7E8C1E            ; constant blank cell word ($2002): the queue DMAs later, so a
                                ; space queued in the same frame as a glyph needs its own source

; dynamic 8x8 glyph cache for the match screens (font at BG3 base, 16 bytes per tile)
GLYPH8  = $B38000               ; 16 bytes per glyph id
POOL8   = $B1BE00               ; u16 count, then the free font slots
D_MAP   = $7E9A80               ; glyph id held by each pool slot (u16 each)
; roster screens ($82:EA7B surname rows, $82:EB1F defensive-shift rows): the same 8x8
; cache idea with the menu font's kana columns as the pool
MPOOL   = $B1BE80               ; u16 count, then the menu font slots
M_MAP   = $7E9B20               ; glyph id per menu pool slot (u16 each, up to 96)
M_NEXT  = GST+14
M_BUF   = $7E9BE0               ; cell buffer (low word, bank $7E)
M_CELLS = $7E9BE2
SHIFT_TABLE = $B1BD00           ; 4-byte entries: low word = string address in bank $B1
; VRAM queue hook: rows queued straight from ROM (player-info labels and values)
ROWS8   = $B1A000               ; u16 count, entries (u8 bank, u16 addr, u16 string), strings
ROWBUF  = $7E8C40               ; 15 rotating 64-byte row buffers ($8C40-$8FFF): a menu queues up to
ROWBUFS = 15                    ; 14 rows before the NMI drains them
M_ROW   = $7E9BE4
Q_A     = $7E9BE6
Q_X     = $7E9BE8
Q_Y     = $7E9BEA
Q_DB    = $7E9BEC
Q_CNT   = $7E9BEE
Q_STR   = $7E9BF0
Q_ATTR  = $7E9BF2
Q_BUF   = $7E9BF4
Q_CELLS = $7E9BF6
QUEUE_CONT = $80F102            ; after the replaced PHP / PHB / PEA $007E
; decompressed-sheet hook ($81:858A): DP $20 = source in bank $7F, $22 = bytes, $18 = VRAM word
SPRTEXT = $B48000               ; u16 count, entries of (32-byte signature, 32-byte Korean tile)
SPRBITS = $B4C000               ; 8 KB bitmap of signature first words (quick reject)
MAPLABELS = $B4E000             ; u16 count, entries (u16 buffer offset, u16 original word, u16 n, u16 label id)
LABELSITES = $B4E800            ; u16 count, entries (u8 bank, u16 row address, u16 id + $1000 for row 2)
T_ADDR  = $7E8C28               ; site_find scratch
T_BANK  = $7E8C2A
T_CNT   = $7E8C2C
T_VAL   = $7E8C2E               ; site_find result (label id + row flag)
MVN_CONT = $90CA98              ; after the replaced PHP / PHB / REP #$30 of the MVN row copier
S_WORD  = $7E8C26
S_TILE  = $7E9BF8
S_ENT   = $7E9BFA
S_CNT   = $7E9BFC
S_END   = $7E9BFE
S_CALLS = $7E8C20               ; debug: cmd 1C upload calls seen
S_LASTBANK = $7E8C22
S_LASTSRC  = $7E8C24
SHEET_SKIP = $8185B5            ; PLP / RTS (byte count zero)
SHEET_CONT = $81858E            ; STZ $420C ... the DMA itself
SHEET2_CONT = $819302           ; after PHP PHB PHK PLB of the cmd 1C upload routine
ROSTER_NAME_RTS  = $82EACC
ROSTER_SHIFT_RTS = $82EB6F
ROSTER_ITEM_RTS  = $82EB1E
ROSTER_W4_EXIT   = $82C35A      ; the lineup task's row-queue code (PEA $0000 / PLB / PLP)
ROSTER_FULL_RTS  = $90B99E
ROSTER_FULL7F_CONT = $9094A5
W4_ATTR_FLAG     = $7E6886      ; nonzero: palette 1 ($2400) instead of 0 ($2000)

; ---- pre-drawn labels (menus, team names): hook on the row writer $91B390 ----
ORIG_ROW_WRITER = $11B395       ; after PHP PHB PHD REP #$30
ROW_OFFSET      = $91AE1E       ; X=col Y=row -> A = window buffer offset
CELL_PUT        = $91B373       ; A=word Y=offset -> current window buffer
ROW_DIRTY_MASK  = $91AE6C
ROW_DIRTY_SET   = $91AD72
LABEL_TABLE     = $B1C000       ; u16 string address per label id (strings follow, bank $B1)
LABEL_MARK      = $C000         ; word 0 of a translated row: %11tt iiii iiii iiii (t=0 top, 1 bottom)
RESERVED        = $B1BF00       ; 512-bit map of kanji-area tiles still used by untranslated labels
POOL_TILES      = 512
LMAP            = $7EA400       ; cache map: 36 entries of (id, columns, unused) = 6 bytes
LMAP_ENTRIES    = 36
LTILES          = $7EA500       ; per map entry: 66 tile numbers (top row cells, then bottom row)
LTILES_STRIDE   = 132           ; ends at $7EB767
STAGE           = $7E8800       ; render staging: up to 33 columns x 2 tile rows ($8800-$8C1F)
RING            = $7E9840       ; pending tile uploads: 32 entries of (VRAM word address, 16 bytes)
RING_ENTRY      = 18
RING_ENTRIES    = 32
RING_BYTES      = RING_ENTRY*RING_ENTRIES
RING_DRAIN      = 24            ; tiles uploaded per NMI
LST             = $7E14C0       ; label state
L_BASE    = LST+0               ; BG3 name base nibble the pool was set up for
L_POOL0   = LST+2               ; first pool tile number
L_POOLN   = LST+4               ; pool size in tiles
L_NEXT    = LST+6               ; next free tile (relative to pool start)
R_HEAD    = LST+8               ; ring read offset (NMI)
R_TAIL    = LST+10              ; ring write offset (main thread)
L_MAPN    = LST+14              ; entries used in the cache map
L_VRAMW   = LST+16              ; VRAM word address of pool tile 0

; scratch direct page used while drawing a glyph
Z       = $1400
z_idx   = $00
z_w     = $02
z_ptr   = $04
z_spill = $08
z_row   = $0A
z_dst   = $0C
z_shift = $0E
z_val   = $10
z_tmp   = $12
z_col   = $14
z_base  = $16                   ; byte offset of the target tile image in bank $7E
z_stride = $18                  ; bytes between neighbouring columns
z_botoff = $1A                  ; bytes from the top tile of a column to its bottom tile
z_maxpx = $1C                   ; right limit for glyph drawing
z_pen   = $1E                   ; pen position used by draw_glyph (copied back to PEN_X for dialogue)
z_tpl   = $20                   ; label hook temporaries
z_id    = $22
z_cols  = $24
z_tile  = $26
z_n     = $28
z_attr  = $2A
z_x     = $2C
z_y     = $2E
z_ent   = $30                   ; byte offset of the cache entry's tile list
z_i     = $32
z_mode  = $34                   ; 1 = 8px-font label (string starts with $01)
z_buf   = $36                   ; 24-bit destination pointer of label_write_buf ($36-$38)

.segment "CODE"

; ---- fixed entry table (addresses used by build.py) --------------------------
        jml kbb_start           ; $B18000
        jml kbb_main_loop       ; $B18004
        jml kbb_nested_loop     ; $B18008
        jml kbb_nmi             ; $B1800C
        jml kbb_label_row       ; $B18010
        jml kbb_game_start      ; $B18014
        jml kbb_game_main       ; $B18018
        jml kbb_game_nested     ; $B1801C
        jml kbb_hud_name        ; $B18020
        jml kbb_roster_name     ; $B18024
        jml kbb_roster_shift    ; $B18028
        jml kbb_roster_item     ; $B1802C
        jml kbb_roster_w4       ; $B18030
        jml kbb_roster_full     ; $B18034
        jml kbb_roster_full7f   ; $B18038
        jml kbb_queue           ; $B1803C
        jml kbb_sheet           ; $B18040
        jml kbb_sheet2          ; $B18044
        jml kbb_mvn             ; $B18048

bit_table:
        .word $0001, $0002, $0004, $0008, $0010, $0020, $0040, $0080
cache_table:                    ; first cache tile by BG3 name base nibble
        .word $0300, $0300, $0300, $0300, $0300, $0100, $0300, $0300

; ---- message start (replaces LDA $02 / STA $06 at $10:EA21) ------------------
.a16
.i16
kbb_start:
        lda T_X
        sta T_X0
        sta f:XCOL0
        lda #0
        sta f:PEN_X
        sta f:LINE
        sta f:MODE
        ; columns available up to the right screen edge, at most 31
        lda #32
        sec
        sbc T_X
        cmp #BUF_COLS-2
        bcc @cols_ok
        lda #BUF_COLS-2
@cols_ok:
        sta f:NCOLS
        asl
        asl
        asl
        sta f:MAX_PX
        jsr cache_setup
        ; fill the window tilemap with cache tile numbers
        lda #0
        sta f:C_COL
@col:   lda #0
        sta f:C_ROW
@row:   lda f:C_COL
        asl
        asl
        clc
        adc f:C_ROW
        clc
        adc f:CTILE
        ora #$2000
        pha
        lda T_Y
        dec
        clc
        adc f:C_ROW
        tay
        lda T_X
        clc
        adc f:C_COL
        tax
        pla
        jsl TILEMAP_PUT
        lda f:C_ROW
        inc
        sta f:C_ROW
        cmp #4
        bne @row
        lda f:C_COL
        inc
        sta f:C_COL
        cmp f:NCOLS
        bne @col
        ; upload everything once
        lda #(BUF_COLS-1)*256
        sta f:RANGE
        lda #FLAG_MAGIC
        sta f:FLAG
        jml ORIG_WAIT

; Cache location from the BG3 name base, then clear the tile buffer.
cache_setup:
        lda f:BG34NBA_SHADOW
        and #$0007
        asl
        tax
        lda f:cache_table,x
        sta f:CTILE
        lda f:BG34NBA_SHADOW
        and #$0007
        xba                     ; nibble << 8
        asl
        asl
        asl
        asl                     ; nibble << 12 = word address of the name base
        sta f:VRAMW
        lda f:CTILE
        asl
        asl
        asl                     ; tile * 8 words
        clc
        adc f:VRAMW
        sta f:VRAMW
        ldx #0
        lda #0
@clr:   sta f:BUF,x
        inx
        inx
        cpx #BUF_SIZE
        bne @clr
        rts

; ---- main string loop (replaces the loop head at $10:EA2B) -------------------
kbb_main_loop:
        lda T_WIN
        sta f:WINDOW_SEL
        ; numbers printed by the original code advance T_X in tiles; catch up
        lda T_X
        sec
        sbc f:XCOL0
        asl
        asl
        asl
        cmp f:PEN_X
        bcc @synced
        beq @synced
        sta f:PEN_X
@synced:
        ldy T_PTR
        lda $0000,y             ; DB = script bank
        and #$00FF
        beq @end
        cmp #$00A0
        beq @newline
        cmp #$0002
        beq @space
        cmp #$00F0
        beq @var
        jsr get_index
        sty T_PTR
        jsr draw_glyph
        jsr sfx
        jml ORIG_WAIT
@end:   jml ORIG_END
@newline:
        inc T_PTR
        jsr do_newline
        jmp kbb_main_loop
@space:
        inc T_PTR
        ldy T_PTR
        jsr do_space
        jmp kbb_main_loop
@var:
        jsr sync_col
        jml ORIG_VAR

; ---- nested string loop (replaces the loop head at $10:EBF7) -----------------
kbb_nested_loop:
        lda T_WIN
        sta f:WINDOW_SEL
        ldy T_NPTR
        lda $0000,y
        and #$00FF
        beq @end
        cmp #$00F0
        beq @end
        cmp #$00A0
        beq @newline
        cmp #$0002
        beq @space
        jsr get_index
        sty T_NPTR
        jsr draw_glyph
        jsr sfx
        jml ORIG_NEST_WAIT
@end:   jml ORIG_NEST_END
@newline:
        inc T_NPTR
        jsr do_newline
        jmp kbb_nested_loop
@space:
        inc T_NPTR
        ldy T_NPTR
        jsr do_space
        jmp kbb_nested_loop

; ---- helpers -----------------------------------------------------------------
; A = first byte (0..FF), Y = its address -> A = glyph index, Y = next address
get_index:
        cmp #$0080
        bcs @two
        iny
        rts
@two:   and #$001F
        xba                     ; (b0 & 1F) << 8
        sta f:z_tmp+Z+$7E0000
        iny
        lda $0000,y
        and #$00FF
        ora f:z_tmp+Z+$7E0000
        clc
        adc #$0080
        iny
        rts

; A = pixel width of label string z_id (DP = Z)
label_width:
        phb
        pea $B1B1
        plb
        plb
        lda #0
        sta z_pen
        sta z_mode
        lda z_id
        asl
        tax
        lda f:LABEL_TABLE,x
        tay
        lda $0000,y
        and #$00FF
        cmp #$0001
        bne @ch
        iny
        inc z_mode
@ch:    lda $0000,y
        and #$00FF
        beq @end
        cmp #$0002
        beq @sp
        cmp #$00A0
        beq @skip1
        cmp #$00F0
        beq @skip2
        jsr get_index
        tax
        lda f:WIDTHS,x
        and #$00FF
        clc
        adc z_pen
        sta z_pen
        bra @ch
@sp:    lda z_pen
        clc
        adc #SPACE_W
        sta z_pen
@skip1: iny
        bra @ch
@skip2: iny
        iny
        bra @ch
@end:   plb
        lda z_pen
        rts

; T_X = XCOL0 + ceil(PEN_X / 8)
sync_col:
        lda f:PEN_X
        clc
        adc #7
        lsr
        lsr
        lsr
        clc
        adc f:XCOL0
        sta T_X
        rts

do_newline:
        lda f:LINE
        cmp #MAX_LINES-1
        bcs @overflow
        inc
        sta f:LINE
        lda f:MODE
        bne @nl_ok
        lda T_Y
        inc
        inc
        sta T_Y
@nl_ok: lda #0
        bra @set
@overflow:
        lda #OVERFLOW_X         ; no room left: drop the rest of the message
@set:   sta f:PEN_X
        lda f:MODE
        bne @done
        lda f:XCOL0
        sta T_X
@done:  rts

; Y = address of the word after the space. Wraps if the word does not fit.
do_space:
        jsr measure_word
        clc
        adc f:PEN_X
        clc
        adc #SPACE_W
        cmp f:MAX_PX
        bcc @fits
        beq @fits
        jmp do_newline
@fits:  lda f:PEN_X
        clc
        adc #SPACE_W
        sta f:PEN_X
        rts

; Y = address -> A = pixel width of the glyphs up to the next 00/02/A0/F0
measure_word:
        lda #0
        sta f:z_val+Z+$7E0000
@next:  lda $0000,y
        and #$00FF
        beq @done
        cmp #$0002
        beq @done
        cmp #$00A0
        beq @done
        cmp #$00F0
        beq @done
        jsr get_index
        tax
        lda f:WIDTHS,x
        and #$00FF
        clc
        adc f:z_val+Z+$7E0000
        sta f:z_val+Z+$7E0000
        bra @next
@done:  lda f:z_val+Z+$7E0000
        rts

sfx:
        lda f:SFX_FLAG
        beq @no
        lda #$0035
        jsl SFX_PLAY
@no:    rts

; A = glyph index. Draws it into the dialogue buffer at PEN_X on LINE.
draw_glyph:
        phd
        pea Z
        pld
        pha
        lda f:PEN_X
        sta z_pen
        lda #(BUF_COLS-2)*8
        sta z_maxpx
        lda #.loword(BUF)
        sta z_base
        lda #64
        sta z_stride
        lda #16
        sta z_botoff
        lda f:LINE
        asl
        asl
        asl
        asl
        asl                     ; line * 32 (two tile rows)
        clc
        adc z_base
        sta z_base
        pla
        jsr blit_glyph
        bcc @nodraw
        lda z_pen
        sta f:PEN_X
        ; dirty range: columns z_col .. z_col+2 (union with the pending range)
        lda f:RANGE
        sta z_tmp
        sep #$20
        lda z_col
        cmp z_tmp
        bcs @lo_ok
        sta z_tmp
@lo_ok: lda z_col
        inc
        inc
        cmp z_tmp+1
        bcc @hi_ok
        sta z_tmp+1
@hi_ok: rep #$20
        lda z_tmp
        sta f:RANGE
        lda #FLAG_MAGIC
        sta f:FLAG
@nodraw:
        pld
        rts

; A = glyph index; DP = Z with z_pen/z_base/z_stride/z_botoff/z_maxpx set.
; Draws into the tile image and advances z_pen. Carry set if drawn.
blit_glyph:
        sta z_idx
        tax
        lda f:WIDTHS,x
        and #$00FF
        sta z_w
        clc
        adc z_pen
        cmp z_maxpx
        bcc @fits
        beq @fits
        clc
        rts
@fits:
        ; bitmap pointer
        lda z_idx
        and #$03FF
        asl
        asl
        asl
        asl
        asl
        clc
        adc #$8000
        sta z_ptr
        lda z_idx
        xba
        lsr
        lsr
        and #$003F
        clc
        adc #GLYPH_BANK0
        sep #$20
        sta z_ptr+2
        rep #$20
        ; destination column / shift
        lda z_pen
        and #$0007
        sta z_shift
        lda z_pen
        lsr
        lsr
        lsr
        sta z_col
        ; z_dst = z_base + col * stride
        lda #0
        ldx z_col
        beq @mul_done
        clc
@mul:   adc z_stride
        dex
        bne @mul
@mul_done:
        clc
        adc z_base
        sta z_dst
        lda #0
        sta z_row
@row:   lda z_row
        asl
        tay
        lda [z_ptr],y
        jsr plot_row
        inc z_row
        lda z_row
        cmp #16
        bne @row
        lda z_pen
        clc
        adc z_w
        sta z_pen
        sec
        rts

; OR one glyph row (A = 16 bits, leftmost pixel in bit 15) shifted right by z_shift into
; both planes of the tile column at z_dst, row z_row (0..15).
plot_row:
        ldx #0
        stx z_spill
        ldx z_shift
        beq @shifted
@sh:    lsr
        ror z_spill
        dex
        bne @sh
@shifted:
        sta z_val
        lda z_row
        and #$0007
        asl
        sta z_tmp
        lda z_row
        and #$0008
        beq @upper
        lda z_botoff
@upper: clc
        adc z_tmp
        clc
        adc z_dst
        tax                     ; X = byte offset of the column's tile row
        sep #$20
        lda z_val+1
        ora f:$7E0000,x
        sta f:$7E0000,x
        lda z_val+1
        ora f:$7E0001,x
        sta f:$7E0001,x
        rep #$20
        txa
        clc
        adc z_stride
        tax
        sep #$20
        lda z_val
        ora f:$7E0000,x
        sta f:$7E0000,x
        lda z_val
        ora f:$7E0001,x
        sta f:$7E0001,x
        rep #$20
        txa
        clc
        adc z_stride
        tax
        sep #$20
        lda z_spill+1
        ora f:$7E0000,x
        sta f:$7E0000,x
        lda z_spill+1
        ora f:$7E0001,x
        sta f:$7E0001,x
        rep #$20
        rts

; ---- label hook: replaces PHP PHB PHD REP #$30 at $91B390 -------------------
; Entry state is the caller's: A = row data address (in DB), X = column,
; Y = row, stack: [return 3][n 2][attr 2]. Translated rows start with a marker
; word; anything else continues in the original writer.
kbb_label_row:
        php
        rep #$30
        pha
        phx
        phy
        lda #0
        sta f:T_BANK
        sep #$20
        phb
        pla
        sta f:T_BANK            ; the row data bank is the caller's DB
        rep #$30
        lda f:T_BANK
        tay
        lda 5,s                 ; the saved A: the row data address
        jsr site_find
        bcs @marked
        ply
        plx
        pla
        plp
        php                     ; re-execute the replaced instructions
        phb
        phd
        rep #$30
        jml ORIG_ROW_WRITER
@marked:
        phb
        phd
        pea Z
        pld
        ; stack from S+1: D(2) B(1) Y(2) X(2) A(2) P(1) ret(3) n(2) attr(2)
        lda f:T_VAL
        ora #$C000
        sta z_tpl
        and #$0FFF
        sta z_id
        lda 4,s
        sta z_y
        lda 6,s
        sta z_x
        lda 14,s
        and #$00FF
        sta z_n
        lda 16,s
        sta z_attr
        jsr label_body
        pld
        plb
        ply
        plx
        pla
        plp
        rtl

; A = row address, Y = bank. Carry set and A = T_VAL (label id + row flag) when that row is a
; translated label. Independent of DP, DB and the row's own contents.
site_find:
        sta f:T_ADDR
        tya
        and #$007F              ; the game reaches ROM through the $80+ mirrors too
        sta f:T_BANK
        lda f:LABELSITES
        sta f:T_CNT
        ldx #2
@loop:  lda f:T_CNT
        beq @miss
        dec
        sta f:T_CNT
        lda f:LABELSITES,x
        and #$00FF
        cmp f:T_BANK
        bne @next
        lda f:LABELSITES+1,x
        cmp f:T_ADDR
        beq @hit
@next:  txa
        clc
        adc #5
        tax
        bra @loop
@hit:   lda f:LABELSITES+3,x
        sta f:T_VAL
        sec
        rts
@miss:  clc
        rts

; DP = Z. Draws label z_id (top or bottom row per z_tpl bit 12) at z_x/z_y, z_n cells.
label_body:
        jsr label_prepare
        jmp label_write_win

; DP = Z. Finds label z_id in the pool cache (or allocates and paints it); z_cols/z_ent set.
label_prepare:
        jsr pool_setup
        lda f:L_MAPN
        sta z_tmp
        ldx #0
@find:  cpx z_tmp
        bcs @miss
        lda f:LMAP,x
        cmp z_id
        beq @hit
        txa
        clc
        adc #6
        tax
        bra @find
@hit:   lda f:LMAP+2,x
        sta z_cols
        txa
        jsr entry_offset
        jmp label_paint         ; the scene may have reloaded the font block: send again
@miss:  jmp label_render

; Write the prepared label's cells through the game's window buffer at z_x/z_y.
label_write_win:
        ldx z_x
        ldy z_y
        jsl ROW_OFFSET
        tay
        lda #0
        sta z_i
@cell:  lda z_i
        cmp z_cols
        bcs @blank
        lda z_tpl
        and #$1000
        beq @top
        lda z_i
        clc
        adc z_cols
        bra @idx
@top:   lda z_i
@idx:   asl
        clc
        adc z_ent
        tax
        lda f:LTILES,x
        clc
        adc f:L_POOL0
        bra @put
@blank: lda #0
@put:   ora z_attr
        jsl CELL_PUT
        iny
        iny
        inc z_i
        lda z_i
        cmp z_cols
        bcc @cell
        cmp z_n
        bcc @cell
        ldy z_y
        jsl ROW_DIRTY_MASK
        jsl ROW_DIRTY_SET
        rts

; Write the prepared label's cells straight to memory at [z_buf] (tilemap buffers, the MVN
; copier's destination, the queue row buffer); max(z_cols, z_n) words, the extra ones blank.
label_write_buf:
        lda #0
        sta z_i
@cell:  lda z_i
        cmp z_cols
        bcs @blank
        lda z_tpl
        and #$1000
        beq @top
        lda z_i
        clc
        adc z_cols
        bra @idx
@top:   lda z_i
@idx:   asl
        clc
        adc z_ent
        tax
        lda f:LTILES,x
        clc
        adc f:L_POOL0
        bra @put
@blank: lda #0
@put:   ora z_attr
        sta [z_buf]
        inc z_buf
        inc z_buf
        inc z_i
        lda z_i
        cmp z_cols
        bcc @cell
        cmp z_n
        bcc @cell
        rts

; A = byte offset of a map entry (k*6) -> z_ent = k * LTILES_STRIDE
entry_offset:
        lsr                     ; k*3
        sta z_tmp
        asl                     ; k*6
        asl                     ; k*12
        asl                     ; k*24
        asl                     ; k*48
        sta z_ent
        asl                     ; k*96
        clc
        adc z_ent               ; k*144
        sec
        sbc z_tmp               ; k*141
        sec
        sbc z_tmp               ; k*138
        sec
        sbc z_tmp               ; k*135
        sec
        sbc z_tmp               ; k*132
        sta z_ent
        rts

; (Re)initialise the tile pool when the BG3 name base changed.
pool_setup:
        lda f:BG34NBA_SHADOW
        and #$0007
        cmp f:L_BASE
        bne @init
        lda f:L_POOLN
        bne @done
@init:  lda f:BG34NBA_SHADOW
        and #$0007
        sta f:L_BASE
        beq @big
        cmp #2
        beq @big
        ; other scenes (story $A000, in-game $C000): 124 tiles right after the dialogue cache
        asl
        tax
        lda f:cache_table,x
        clc
        adc #BUF_COLS*4
        sta f:L_POOL0
        lda #124
        sta f:L_POOLN
        bra @range
@big:   lda #$0100              ; the 16x16 kanji font area, unused once labels are Korean
        sta f:L_POOL0
        lda #POOL_TILES
        sta f:L_POOLN
@range: lda #0
        sta f:L_NEXT
        sta f:L_MAPN
        lda f:L_BASE
        xba
        asl
        asl
        asl
        asl
        sta f:L_VRAMW
        lda f:L_POOL0
        asl
        asl
        asl
        clc
        adc f:L_VRAMW
        sta f:L_VRAMW
@done:  rts

; Allocate 2 * cols pool tiles (skipping reserved ones) for label z_id in a new
; cache entry, then paint. cols = max(n, ceil(width / 8)), at most n + 4 and never
; past the screen edge.
label_render:
        jsr label_width         ; A = pixel width of the string
        clc
        adc #7
        lsr
        lsr
        lsr
        cmp z_n
        bcs @wide
        lda z_n
@wide:  sta z_cols
        lda z_n
        clc
        adc #4
        cmp z_cols
        bcs @cap1
        sta z_cols
@cap1:  lda #32
        sec
        sbc z_x
        cmp z_cols
        bcs @cap2
        sta z_cols
@cap2:  lda #0
        sta z_row               ; wrap counter
@entry: lda f:L_MAPN
        cmp #LMAP_ENTRIES*6
        bcc @map_ok
        lda #0
        sta f:L_MAPN
        sta f:L_NEXT
@map_ok:
        jsr entry_offset        ; z_ent from the entry byte offset in A
        lda #0
        sta z_i
@tile:  lda f:L_NEXT
        cmp f:L_POOLN
        bcc @in_pool
        lda #0                  ; pool exhausted: start over and redo this label
        sta f:L_NEXT
        sta f:L_MAPN
        inc z_row
        jmp @entry
@in_pool:
        lda f:L_POOL0
        cmp #$0100
        bne @take               ; reservations only apply to the kanji-font pool
        lda z_row
        cmp #2
        bcs @take               ; wrapped twice: ignore reservations
        lda f:L_NEXT
        lsr
        lsr
        lsr
        tax
        lda f:RESERVED,x
        and #$00FF
        sta z_spill
        lda f:L_NEXT
        and #$0007
        asl
        tax
        lda f:bit_table,x
        and z_spill
        beq @take
        lda f:L_NEXT
        inc
        sta f:L_NEXT
        jmp @tile
@take:  lda f:L_NEXT
        sta z_tile
        inc
        sta f:L_NEXT
        lda z_i
        asl
        clc
        adc z_ent
        tax
        lda z_tile
        sta f:LTILES,x
        inc z_i
        lda z_cols
        asl
        cmp z_i
        beq @alloc_done
        jmp @tile
@alloc_done:
        lda f:L_MAPN
        tax
        clc
        adc #6
        sta f:L_MAPN
        lda z_id
        sta f:LMAP,x
        lda z_cols
        sta f:LMAP+2,x
        ; fall through into label_paint

; Render label z_id into staging (2 * z_cols tiles) and queue every tile of the
; entry at z_ent for upload.
label_paint:
        lda z_cols
        asl
        asl
        asl
        asl
        asl                     ; cols * 32 bytes
        sta z_tmp
        ldx #0
        lda #0
@clr:   sta f:STAGE,x
        inx
        inx
        cpx z_tmp
        bne @clr
        lda #.loword(STAGE)
        sta z_base
        lda #16
        sta z_stride
        lda z_cols
        asl
        asl
        asl
        asl
        sta z_botoff
        lda z_cols
        asl
        asl
        asl
        sta z_maxpx
        jsr label_width         ; also sets z_mode from the string's prefix
        ldx z_mode
        beq @left
        sta z_tmp               ; centred labels start half the slack in
        lda z_maxpx
        sec
        sbc z_tmp
        bcc @left
        lsr
        sta z_pen
        bra @go
@left:  lda #0
        sta z_pen
@go:    phb
        pea $B1B1
        plb
        plb
        lda z_id
        asl
        tax
        lda f:LABEL_TABLE,x
        tay
        lda $0000,y
        and #$00FF
        cmp #$0001
        bne @ch
        iny
@ch:    lda $0000,y
        and #$00FF
        beq @end
        cmp #$0002
        beq @sp
        cmp #$00A0
        beq @skip1
        cmp #$00F0
        beq @skip2
        jsr get_index
        phy
        jsr blit_glyph
        ply
        bra @ch
@sp:    lda z_pen
        clc
        adc #SPACE_W
        sta z_pen
@skip1: iny
        bra @ch
@skip2: iny
        iny
        bra @ch
@end:   plb
        lda #0
        sta z_i
@push:  lda z_i
        asl
        clc
        adc z_ent
        tax
        lda f:LTILES,x
        asl
        asl
        asl
        clc
        adc f:L_VRAMW
        sta z_val               ; VRAM word address
        lda z_i
        asl
        asl
        asl
        asl
        clc
        adc #.loword(STAGE)
        sta z_dst               ; source bytes
        jsr ring_push
        inc z_i
        lda z_cols
        asl
        cmp z_i
        bne @push
        rts

; Append (z_val = VRAM word, 16 bytes at z_dst) to the upload ring. Waits for the
; NMI to make room; gives up after a while so a scene with NMI disabled cannot hang.
ring_push:
        lda #$4000
        sta z_spill             ; timeout
@wait:  lda f:R_TAIL
        clc
        adc #RING_ENTRY
        cmp #RING_BYTES
        bcc @nowrap
        lda #0
@nowrap:
        cmp f:R_HEAD
        bne @room
        dec z_spill
        bne @wait
        rts                     ; ring stuck full: drop this tile
@room:  sta z_shift             ; next tail
        lda f:R_TAIL
        tax
        lda z_val
        sta f:RING,x
        phy
        ldy #0
@cp:    phx
        tya
        clc
        adc z_dst
        tax
        lda f:$7E0000,x
        plx
        inx
        inx
        sta f:RING,x
        iny
        iny
        cpy #16
        bne @cp
        ply
        lda z_shift
        sta f:R_TAIL
        rts

; ---- in-game text: 8x8 dynamic glyph cache ----------------------------------
; A = glyph id -> A = font tile number. Misses take the next pool slot and queue
; the tile bytes (Galmuri7) for upload. DP-free; clobbers X, Y.
d_get:
        sta f:D_ID
        lda #0
        sta f:D_TMP             ; slot index
@scan:  lda f:D_TMP
        cmp f:POOL8             ; count
        bcs @miss
        asl
        tax
        lda f:D_MAP,x
        cmp f:D_ID
        beq @hit
        lda f:D_TMP
        inc
        sta f:D_TMP
        bra @scan
@hit:   lda f:D_TMP
        tax
        lda f:POOL8+2,x
        and #$00FF
        sta f:D_TMP
        bra @send               ; re-send: a view change may have reloaded the font block
@miss:  lda f:D_NEXT
        cmp f:POOL8
        bcc @slot
        lda #0
@slot:  sta f:D_TMP
        inc
        sta f:D_NEXT
        lda f:D_TMP
        asl
        tax
        lda f:D_ID
        sta f:D_MAP,x
        lda f:D_TMP
        tax
        lda f:POOL8+2,x
        and #$00FF
        sta f:D_TMP             ; tile
@send:  ; VRAM word = (BG3 base nibble << 12) + tile * 8
        lda f:BG34NBA_SHADOW
        and #$0007
        xba
        asl
        asl
        asl
        asl
        sta f:z_val+Z+$7E0000
        lda f:D_TMP
        asl
        asl
        asl
        clc
        adc f:z_val+Z+$7E0000
        sta f:z_val+Z+$7E0000
        lda f:D_ID
        asl
        asl
        asl
        asl
        clc
        adc #.loword(GLYPH8)
        sta f:z_dst+Z+$7E0000
        jsr ring_push_rom
        lda f:D_TMP
        rts

; Append (z_val = VRAM word, 16 bytes at GLYPH8 bank offset z_dst) to the upload ring.
ring_push_rom:
        lda #$4000
        sta f:z_spill+Z+$7E0000
@wait:  lda f:R_TAIL
        clc
        adc #RING_ENTRY
        cmp #RING_BYTES
        bcc @nowrap
        lda #0
@nowrap:
        cmp f:R_HEAD
        bne @room
        lda f:z_spill+Z+$7E0000
        dec
        sta f:z_spill+Z+$7E0000
        bne @wait
        rts
@room:  sta f:z_shift+Z+$7E0000
        lda f:R_TAIL
        tax
        lda f:z_val+Z+$7E0000
        sta f:RING,x
        ldy #0
@cp:    phx
        tya
        clc
        adc f:z_dst+Z+$7E0000
        tax
        lda f:GLYPH8&$FF0000,x
        plx
        inx
        inx
        sta f:RING,x
        iny
        iny
        cpy #16
        bne @cp
        lda f:z_shift+Z+$7E0000
        sta f:R_TAIL
        rts

; ---- HUD player name: replaces LDA $22 / ASL / TAX at $0E:F7B2 -------------
; DP = task frame with $00-$0F (upper row) and $10-$1F (name row) already blank.
kbb_hud_name:
        lda $22
        asl
        tax
        lda f:$7E307F,x
        asl
        asl
        tax
        pea SCRIPT_BANK*256+SCRIPT_BANK
        plb
        plb
        lda a:SURNAME_TABLE,x
        tay
        ldx #0
@ch:    lda $0000,y
        and #$00FF
        beq @done
        cmp #$0002
        beq @space
        cmp #$0080
        bcs @glyph
        cmp #$00A0
        bcs @skip               ; control bytes above the glyph range
@glyph: phx
        jsr get_index
        phy
        jsr d_get
        ply
        plx
        ora #$2000
        sta $10,x
        inx
        inx
        cpx #HUD_CELLS*2
        bcc @ch
        bra @done
@space: iny
        inx
        inx
        cpx #HUD_CELLS*2
        bcc @ch
        bra @done
@skip:  iny
        bra @ch
@done:  jml HUD_NAME_CONT

; ---- in-game commentary hooks (8x8 cells written through the VRAM queue) -----
; Message start: replaces TAX / BRL $CC37 at $04:CB34 (G_PTR already holds the string).
kbb_game_start:
        lda #$2002
        sta f:G_BLANK
        lda #1
        sta f:MODE
        lda #0
        sta f:LINE
        sta f:G_DROP
        sta f:G_COL
        lda f:G_CELL
        sta f:G_BASE
        jml GAME_MAIN_HEAD

; write cell word A at G_CELL through the queue, then G_CELL++ / G_COL++
game_put_cell:
        sta f:G_CELLWORD
        ldx #.loword(G_CELLWORD)
game_put_from:                  ; X = WRAM address of the cell word
        phx
        phb
        pea $7E7E
        plb
        plb
@retry: lda f:G_CELL
        tay
        lda 2,s
        tax
        lda #2
        jsl VRAM_QUEUE
        bcc @ok
        lda #0
        jsl TASK_WAIT
        bra @retry
@ok:    plb
        plx
        lda f:G_CELL
        inc
        sta f:G_CELL
        lda f:G_COL
        inc
        sta f:G_COL
        rts

game_newline:
        lda f:LINE
        bne @full
        inc
        sta f:LINE
        lda f:G_BASE
        clc
        adc #GAME_LINE2
        sta f:G_CELL
        lda #0
        sta f:G_COL
        rts
@full:  lda #1
        sta f:G_DROP
        rts

; Y = address of the next word -> A = number of glyphs up to the next 00/02/A0/F0
game_word_cells:
        lda #0
        sta f:z_val+Z+$7E0000
@next:  lda $0000,y
        and #$00FF
        beq @done
        cmp #$0002
        beq @done
        cmp #$00A0
        beq @done
        cmp #$00F0
        beq @done
        jsr get_index
        lda f:z_val+Z+$7E0000
        inc
        sta f:z_val+Z+$7E0000
        bra @next
@done:  lda f:z_val+Z+$7E0000
        rts

; Y = address after the space: wrap if the next word does not fit on this line
game_space:
        jsr game_word_cells
        clc
        adc f:G_COL
        inc
        cmp #GAME_COLS+1
        bcs game_newline
        lda f:G_DROP
        bne @done
        ldx #.loword(G_BLANK)
        jsr game_put_from
@done:  rts

; A = glyph index: draw one 8x8 cell unless the line is full
game_glyph:
        pha
        lda f:G_DROP
        bne @drop
        lda f:G_COL
        cmp #GAME_COLS
        bcc @ok
        jsr game_newline        ; word longer than the line: continue on the next line
        lda f:G_DROP
        bne @drop
@ok:    pla
        jsr d_get
        ora #$2000
        jsr game_put_cell
        rts
@drop:  pla
        rts

; Main string step: replaces LDA $7E6933 at $04:CC37.
kbb_game_main:
        pea SCRIPT_BANK*256+SCRIPT_BANK
        plb
        plb
        lda f:G_PTR
        tay
        lda $0000,y
        and #$00FF
        beq @end
        cmp #$00A0
        beq @newline
        cmp #$0002
        beq @space
        cmp #$00F0
        beq @var
        jsr get_index
        pha
        tya
        sta f:G_PTR
        pla
        jsr game_glyph
        jml GAME_WAIT
@end:   jml GAME_MAIN_CONT
@newline:
        iny
        tya
        sta f:G_PTR
        jsr game_newline
        bra kbb_game_main
@space: iny
        tya
        sta f:G_PTR
        jsr game_space
        bra kbb_game_main
@var:   jml GAME_VAR

; Nested string step: replaces LDA $7E6936 at $04:CB4A and $04:CDA4.
kbb_game_nested:
        pea SCRIPT_BANK*256+SCRIPT_BANK
        plb
        plb
        lda f:G_NPTR
        tay
        lda $0000,y
        and #$00FF
        beq @end
        cmp #$00F0
        beq @end
        cmp #$00A0
        beq @newline
        cmp #$0002
        beq @space
        jsr get_index
        pha
        tya
        sta f:G_NPTR
        pla
        jsr game_glyph
        jml GAME_WAIT
@end:   jml GAME_NEST_END
@newline:
        iny
        tya
        sta f:G_NPTR
        jsr game_newline
        bra kbb_game_nested
@space: iny
        tya
        sta f:G_NPTR
        jsr game_space
        bra kbb_game_nested

; ---- NMI hook: upload the dirty columns to VRAM when flagged ----------------
kbb_nmi:
        php
        rep #$30
        pha
        phx
        phy
        phb
        pea $0000
        plb
        plb
        lda f:FLAG
        cmp #FLAG_MAGIC
        beq @pending
        jmp @done
@pending:
        lda #0
        sta f:FLAG
        ; the cache VRAM address follows the BG3 name base in effect right now: a
        ; message can start while the previous scene's registers are still shadowed
        lda f:BG34NBA_SHADOW
        and #$0007
        asl
        tax
        lda f:cache_table,x
        asl
        asl
        asl
        sta f:N_TMP
        lda f:BG34NBA_SHADOW
        and #$0007
        xba
        asl
        asl
        asl
        asl
        clc
        adc f:N_TMP
        sta f:VRAMW
        lda f:RANGE
        tay                     ; Y = lo | hi << 8
        lda #RANGE_EMPTY
        sta f:RANGE
        tya
        and #$00FF
        tax                     ; X = first column
        sta f:z_tmp+Z+$7E0000
        tya
        xba
        and #$00FF
        cmp #BUF_COLS
        bcs @done
        sec
        sbc f:z_tmp+Z+$7E0000   ; hi - lo
        bcc @done               ; empty range
        inc
        asl
        asl
        asl
        asl
        asl
        asl                     ; columns * 64 bytes
        sta $4365
        txa
        asl
        asl
        asl
        asl
        asl                     ; lo * 32 words
        clc
        adc f:VRAMW
        sta $2116
        txa
        asl
        asl
        asl
        asl
        asl
        asl                     ; lo * 64 bytes
        clc
        adc #.loword(BUF)
        sta $4362
        sep #$20
        lda #^BUF
        sta $4364
        lda #$80
        sta $2115
        lda #$01
        sta $4360
        lda #$18
        sta $4361
        lda #$40
        sta $420B
@done:  rep #$30
        jsr nmi_pool_upload
        plb
        ply
        plx
        pla
        plp
        jml ORIG_NMI

; Upload up to RING_DRAIN queued label tiles (DB = 0, M/X 16-bit).
nmi_pool_upload:
        lda f:R_HEAD
        cmp #RING_BYTES
        bcs @reset
        lda f:R_TAIL
        cmp #RING_BYTES
        bcs @reset
        lda f:R_HEAD
        cmp f:R_TAIL
        bne @go
        rts
@reset: lda #0                  ; indices out of range (uninitialised WRAM): drop the queue
        sta f:R_HEAD
        sta f:R_TAIL
        rts
@go:    sep #$20
        lda #$80
        sta $2115
        lda #$01
        sta $4360
        lda #$18
        sta $4361
        lda #^RING
        sta $4364
        rep #$20
        ldy #RING_DRAIN
@next:  lda f:R_HEAD
        tax
        lda f:RING,x            ; VRAM word address
        sta $2116
        txa
        clc
        adc #.loword(RING)+2
        sta $4362
        lda #16
        sta $4365
        sep #$20
        lda #$40
        sta $420B
        rep #$20
        txa
        clc
        adc #RING_ENTRY
        cmp #RING_BYTES
        bcc @nw
        lda #0
@nw:    sta f:R_HEAD
        cmp f:R_TAIL
        beq @done
        dey
        bne @next
@done:  rts

; ---- roster screens: 8x8 names and shift words from the translated tables ------------
; Replaces LDA $719D / ASL at $82:EA8B and $82:EB2F. DB = $7E, index in $7E:719D,
; attribute word in $7E:719F; the original cleared the cell buffer already.
kbb_roster_name:
        lda #$71AF
        sta f:M_BUF
        lda #6
        sta f:M_CELLS
        lda f:$7E719D
        asl
        asl
        tax
        phb
        pea SCRIPT_BANK*256+SCRIPT_BANK
        plb
        plb
        lda a:SURNAME_TABLE,x
        tay
        jsr roster_cells
        plb
        jml ROSTER_NAME_RTS

kbb_roster_shift:
        lda #$71B3
        sta f:M_BUF
        lda #8
        sta f:M_CELLS
        lda f:$7E719D
        asl
        asl
        tax
        phb
        pea $B1B1
        plb
        plb
        lda a:.loword(SHIFT_TABLE),x
        tay
        jsr roster_cells
        plb
        jml ROSTER_SHIFT_RTS

kbb_roster_item:
        lda #$71B3
        sta f:M_BUF
        lda #8
        sta f:M_CELLS
        lda f:$7E719D
        asl
        asl
        tax
        phb
        pea SCRIPT_BANK*256+SCRIPT_BANK
        plb
        plb
        lda a:ITEM_TABLE,x
        tay
        jsr roster_cells
        plb
        jml ROSTER_ITEM_RTS

kbb_roster_full:
        lda #$71BF
        sta f:M_BUF
        lda #28
        sta f:M_CELLS
        lda f:$7E719D
        asl
        asl
        tax
        phb
        pea SCRIPT_BANK*256+SCRIPT_BANK
        plb
        plb
        lda a:FULLNAME_TABLE,x
        tay
        jsr roster_cells
        plb
        jml ROSTER_FULL_RTS

; Lineup task ($82:C2C5): DP = task frame, DB already the script bank, $32 = string,
; cells at DP $24 (7 max), attribute by W4_ATTR_FLAG. Replaces the loop at $82:C300.
kbb_roster_w4:
        ldy $32
        ldx #0
@ch:    lda $0000,y
        and #$00FF
        beq @done
        cmp #$0002
        beq @space
        cmp #$00A0
        bcs @skip
        cmp #$0003
        bcc @skip1
        phx
        jsr get_index
        phy
        jsr x_get
        ply
        plx
        pha
        lda f:W4_ATTR_FLAG
        bne @pal1
        pla
        ora #$2000
        bra @put
@pal1:  pla
        ora #$2400
@put:   sta $24,x
        inx
        inx
        bra @more
@space: iny
        inx
        inx
@more:  cpx #14
        bcc @ch
@done:  jml ROSTER_W4_EXIT
@skip:  iny
@skip1: iny
        bra @ch

; Player list in the $7F:A000 screen shadow ($90:9456): X = index * 4, Y = cell offset,
; DB = $7F. Continues at the original's end-of-string code.
kbb_roster_full7f:
        phb
        pea SCRIPT_BANK*256+SCRIPT_BANK
        plb
        plb
        lda a:FULLNAME_TABLE,x
        pha
        tya
        sta f:M_BUF
        ply
        ldx #0
@ch:    lda $0000,y
        and #$00FF
        beq @done
        cmp #$0002
        beq @space
        cmp #$00A0
        bcs @skip
        cmp #$0003
        bcc @skip1
        phx
        jsr get_index
        phy
        jsr x_get
        ply
        plx
        ora #$2000
        bra @put
@space: iny
        lda #$2002
@put:   pha
        txa
        clc
        adc f:M_BUF
        tax
        pla
        sta f:$7F0000,x
        txa
        sec
        sbc f:M_BUF
        inc
        inc
        tax
        bra @ch
@done:  plb
        jml ROSTER_FULL7F_CONT
@skip:  iny
@skip1: iny
        bra @ch

; Y = string in DB. Fills up to M_CELLS cells at $7E:M_BUF.
roster_cells:
        ldx #0
@ch:    lda $0000,y
        and #$00FF
        beq @done
        cmp #$0002
        beq @space
        cmp #$00A0
        bcs @skip               ; newline / variable: not expected in names
        cmp #$0003
        bcc @skip1
        phx
        jsr get_index
        phy
        jsr x_get
        ply
        plx
        ora f:$7E719F
        jsr roster_put
        bra @more
@space: iny
        lda #$2002
        jsr roster_put
@more:  txa
        lsr
        cmp f:M_CELLS
        bcc @ch
@done:  rts
@skip:  iny
@skip1: iny
        bra @ch

; A = cell word, X = byte offset in the buffer -> stored; X += 2
roster_put:
        pha
        txa
        clc
        adc f:M_BUF
        tax
        pla
        sta f:$7E0000,x
        txa
        sec
        sbc f:M_BUF
        inc
        inc
        tax
        rts

; A = glyph id -> tile: the in-game cache while a match screen is up (BG3 base nibble 6,
; e.g. the time-out menu), the menu cache otherwise.
x_get:
        pha
        lda f:BG34NBA_SHADOW
        and #$0007
        cmp #6
        beq @game
        pla
        jmp m_get
@game:  pla
        jmp d_get

; A = glyph id -> A = menu font tile (kana column slot); like d_get with its own map.
m_get:
        sta f:D_ID
        lda #0
        sta f:D_TMP
@scan:  lda f:D_TMP
        cmp f:MPOOL
        bcs @miss
        asl
        tax
        lda f:M_MAP,x
        cmp f:D_ID
        beq @hit
        lda f:D_TMP
        inc
        sta f:D_TMP
        bra @scan
@hit:   lda f:D_TMP
        tax
        lda f:MPOOL+2,x
        and #$00FF
        sta f:D_TMP
        bra @send
@miss:  lda f:M_NEXT
        cmp f:MPOOL
        bcc @slot
        lda #0
@slot:  sta f:D_TMP
        inc
        sta f:M_NEXT
        lda f:D_TMP
        asl
        tax
        lda f:D_ID
        sta f:M_MAP,x
        lda f:D_TMP
        tax
        lda f:MPOOL+2,x
        and #$00FF
        sta f:D_TMP
@send:  lda f:BG34NBA_SHADOW
        and #$0007
        xba
        asl
        asl
        asl
        asl
        sta f:z_val+Z+$7E0000
        lda f:D_TMP
        asl
        asl
        asl
        clc
        adc f:z_val+Z+$7E0000
        sta f:z_val+Z+$7E0000
        lda f:D_ID
        asl
        asl
        asl
        asl
        clc
        adc #.loword(GLYPH8)
        sta f:z_dst+Z+$7E0000
        jsr ring_push_rom
        lda f:D_TMP
        rts

; ---- VRAM queue hook: replaces PHP PHB PEA $007E at $80F0FD --------------------------
; X = source in DB, Y = VRAM word, A = bytes. Rows listed in ROWS8 (by caller bank and
; address) are redrawn in Korean through the menu 8x8 cache into a row buffer and queued
; from there; everything else continues in the original routine. A/X/Y and the carry
; result behave as the original.
kbb_queue:
        php
        rep #$30
        pha
        lda #0
        sep #$20
        phb
        pla
        rep #$20
        and #$007F              ; ROM bank number as in the table ($80+ mirrors too)
        cmp #$007E
        bcs @pass0              ; WRAM sources are never translated rows
        sta f:Q_DB
        txa
        sta f:Q_X
        tya
        sta f:Q_Y
        lda f:Q_DB              ; a translated 16x16 row: draw it from the label pool
        tay
        lda f:Q_X
        jsr site_find
        bcc @rows8
        jmp q_label
@rows8: lda f:ROWS8
        sta f:Q_CNT
        ldx #2
@scan:  lda f:Q_CNT
        beq @pass1
        dec
        sta f:Q_CNT
        lda f:ROWS8,x
        and #$00FF
        cmp f:Q_DB
        bne @next
        lda f:ROWS8+1,x
        cmp f:Q_X
        beq @found
@next:  txa
        clc
        adc #5
        tax
        bra @scan
@pass1: lda f:Q_X
        tax
        lda f:Q_Y
        tay
@pass0: pla
        plp
        php
        phb
        pea $007E
        jml QUEUE_CONT
@found: lda f:ROWS8+3,x
        sta f:Q_STR
        pla
        sta f:Q_A
        phb
        lda f:Q_X
        tax
        lda a:$0000,x           ; attribute of the original row
        and #$FC00
        sta f:Q_ATTR
        lda f:M_ROW
        inc
        cmp #ROWBUFS
        bcc *+5
        lda #0
        sta f:M_ROW
        asl
        asl
        asl
        asl
        asl
        asl
        clc
        adc #.loword(ROWBUF)
        sta f:Q_BUF
        lda f:Q_A
        lsr
        cmp #33
        bcc @cells
        lda #32
@cells: sta f:Q_CELLS
        pea $B1B1
        plb
        plb
        lda f:Q_STR
        tay
        ldx #0
@ch:    txa
        lsr
        cmp f:Q_CELLS
        bcs @done
        lda $0000,y
        and #$00FF
        beq @pad
        cmp #$0002
        beq @sp
        cmp #$00A0
        bcs @skip
        cmp #$0003
        bcc @skip1
        phx
        jsr get_index
        phy
        jsr x_get
        ply
        plx
        bra @put
@sp:    iny
        lda #$0002
@put:   ora f:Q_ATTR
        jsr q_store
        bra @ch
@skip:  iny
@skip1: iny
        bra @ch
@pad:   txa
        lsr
        cmp f:Q_CELLS
        bcs @done
        lda f:Q_ATTR
        jsr q_store
        bra @pad
@done:
q_send: pea $7E7E
        plb
        plb
        lda f:Q_BUF
        tax
        lda f:Q_Y
        tay
        lda f:Q_A
        jsl $80F0FD             ; re-enters this hook, which passes WRAM sources through
        plb
        bcs @full
        lda f:Q_X
        tax
        lda f:Q_Y
        tay
        lda f:Q_A
        plp
        clc
        rtl
@full:  lda f:Q_X
        tax
        lda f:Q_Y
        tay
        lda f:Q_A
        plp
        sec
        rtl

; Queue source row that starts with a label marker (stack: P, A = byte count; Q_X / Q_Y set,
; DB = source bank): render the label into the next row buffer and queue that instead.
q_label:
        pla
        sta f:Q_A
        phb
        phd
        pea Z
        pld
        lda f:T_VAL
        ora #$C000
        sta z_tpl
        and #$0FFF
        sta z_id
        lda f:Q_X
        tax
        lda a:$0000,x           ; the row's own attribute bits
        and #$FC00
        sta z_attr
        lda f:Q_A
        lsr
        sta z_n
        lda f:Q_Y
        and #$001F
        sta z_x
        lda f:Q_Y
        lsr
        lsr
        lsr
        lsr
        lsr
        and #$001F
        sta z_y
        lda f:M_ROW
        inc
        cmp #ROWBUFS
        bcc *+5
        lda #0
        sta f:M_ROW
        asl
        asl
        asl
        asl
        asl
        asl
        clc
        adc #.loword(ROWBUF)
        sta f:Q_BUF
        sta z_buf
        lda #$007E
        sta z_buf+2
        jsr label_prepare
        jsr label_write_buf
        lda z_cols
        cmp z_n
        bcs @wide
        lda z_n
@wide:  asl
        sta f:Q_A               ; bytes actually written
        pld
        jmp q_send

; A = cell word, X = byte offset in the row buffer -> stored; X += 2
q_store:
        pha
        txa
        clc
        adc f:Q_BUF
        tax
        pla
        sta f:$7E0000,x
        txa
        sec
        sbc f:Q_BUF
        inc
        inc
        tax
        rts

; ---- decompressed sheet hook: replaces LDA $22 / BEQ at $81:858A ----------------------
; Every 32-byte tile of the buffer that equals a signature in SPRTEXT is overwritten with
; its Korean tile before the game DMAs the sheet to VRAM.
kbb_sheet:
        php
        rep #$30
        lda $22
        bne @go
        jmp @skip
@go:    clc
        adc $20
        sec
        sbc #32                 ; last tile start (a $B000 + $5000 sheet ends exactly at $10000)
        sta f:S_END
        lda $20
        sta f:S_TILE
        phb
        pea $B4B4
        plb
        plb
        jsr sheet_scan
        plb
        plp
        lda $22
        jml SHEET_CONT
@skip:  plp
        lda $22
        jml SHEET_SKIP

; ---- cmd 1C uploads ($81:92FE, source pushed by the caller): same patching --------------
; Entry stack: RTL(3), src low, src high, src bank. X = VRAM word, Y = byte count.
kbb_sheet2:
        php
        rep #$30
        phx
        phy
        lda f:S_CALLS
        inc
        sta f:S_CALLS
        lda 11,s                ; source bank (low byte)
        and #$00FF
        sta f:S_LASTBANK
        lda 9,s
        sta f:S_LASTSRC
        lda 11,s
        and #$00FF
        cmp #$007F
        bne @pass
        lda 9,s                 ; source address
        sta f:S_TILE
        tya
        clc
        adc f:S_TILE
        sec
        sbc #32
        sta f:S_END
        phb
        pea $B4B4
        plb
        plb
        jsr sheet_scan
        plb
        phd
        pea Z
        pld
        jsr map_labels
        pld
@pass:  ply
        plx
        plp
        php                     ; the replaced PHP / PHB / PHK / PLB
        phb
        pea $8181
        plb
        plb
        jml SHEET2_CONT

; DP = Z. Rows of the decompressed tilemap at S_LASTSRC (bank $7F) that still hold the
; original first word of a MAPLABELS entry are redrawn from the label pool (top row at the
; entry's offset, bottom row 64 bytes below).
map_labels:
        lda f:MAPLABELS
        sta z_tmp
        lda #0
        sta z_row               ; pool reset done for this map
        ldx #0
@ent:   lda z_tmp
        bne @go
        rts
@go:    dec
        sta z_tmp
        lda f:MAPLABELS+2,x
        clc
        adc f:S_LASTSRC
        sta z_buf
        lda #$007F
        sta z_buf+2
        phx
        tax
        lda f:$7F0000,x
        plx
        cmp f:MAPLABELS+4,x
        bne @next
        pha
        lda z_row
        bne @reset_done
        inc z_row               ; a labelled screen is being loaded: whatever the pool held is gone
        lda #0
        sta f:L_NEXT
        sta f:L_MAPN
@reset_done:
        pla
        and #$FC00
        sta z_attr
        lda f:MAPLABELS+6,x
        sta z_n
        lda f:MAPLABELS+8,x
        ora #$C000
        sta z_tpl
        and #$0FFF
        sta z_id
        lda f:MAPLABELS+2,x
        and #$003F
        lsr
        sta z_x
        lda f:MAPLABELS+2,x
        lsr
        lsr
        lsr
        lsr
        lsr
        lsr
        sta z_y
        phx
        jsr label_prepare
        jsr label_write_buf
        plx
        lda f:MAPLABELS+2,x
        clc
        adc f:S_LASTSRC
        clc
        adc #64
        sta z_buf
        lda #$007F
        sta z_buf+2
        lda z_tpl
        ora #$1000
        sta z_tpl
        phx
        jsr label_prepare
        jsr label_write_buf
        plx
@next:  txa
        clc
        adc #8
        tax
        jmp @ent

; ---- MVN row copier hook: replaces PHP PHB REP #$30 at $90:CA94 ------------------------
; Entry: A = (source bank << 8) | destination bank, X = source address, Y = destination
; address in bank $7F, stack: [return 3][byte count - 1 (2)]. A ROM row that starts with a
; label marker is drawn from the pool into the destination instead of being copied.
kbb_mvn:
        php
        rep #$30
        pha
        phx
        phy
        phb
        xba
        and #$00FF
        cmp #$007E
        beq @pass
        cmp #$007F
        beq @pass
        tay                     ; Y = source bank
        sep #$20
        pha
        plb                     ; DB = source bank
        rep #$20
        txa
        jsr site_find
        bcc @pass
        lda f:T_VAL
        ora #$C000
        pha                     ; label id + row flag
        lda a:$0002,x
        and #$FC00
        pha                     ; attribute bits of the row
        phd
        pea Z
        pld
        ; stack: D(2) attr(2) marker(2) B(1) Y(2) X(2) A(2) P(1) return(3) count(2)
        lda 5,s
        sta z_tpl
        and #$0FFF
        sta z_id
        lda 3,s
        sta z_attr
        lda 18,s
        inc
        lsr
        sta z_n
        lda 8,s
        sta z_buf
        lda #$007F
        sta z_buf+2
        lda 8,s
        and #$003F
        lsr
        sta z_x
        lda 8,s
        lsr
        lsr
        lsr
        lsr
        lsr
        lsr
        sta z_y
        jsr label_prepare
        jsr label_write_buf
        pld
        pla
        pla
        plb
        ply
        plx
        pla
        plp
        rtl
@pass:  plb
        ply
        plx
        pla
        plp
        php                     ; the replaced PHP / PHB / REP #$30
        phb
        rep #$30
        jml MVN_CONT

; DB = $B4. Replace every tile in [S_TILE, S_END) of bank $7F that matches a signature.
sheet_scan:
@tile:  lda f:S_TILE
        cmp f:S_END
        beq @go
        bcc @go
        jmp @done
@go:    tax                     ; quick reject: is this tile's first word the start of any signature?
        lda f:$7F0000,x
        sta f:S_WORD
        lsr
        lsr
        lsr
        tax
        lda f:SPRBITS,x
        sta f:S_CNT
        lda f:S_WORD
        and #7
        asl
        tax
        lda f:bit_mask,x
        and f:S_CNT
        bne @scan
        jmp @next_tile
@scan:  lda f:SPRTEXT
        sta f:S_CNT
        ldy #2
@ent:   lda f:S_CNT
        beq @next_tile
        dec
        sta f:S_CNT
        tya
        sta f:S_ENT
        lda f:S_TILE
        tax
        lda f:$7F0000,x
        cmp a:.loword(SPRTEXT),y
        bne @nomatch
        inx
        inx
        iny
        iny
        lda #15
@cmp:   pha
        lda f:$7F0000,x
        cmp a:.loword(SPRTEXT),y
        bne @cmp_fail
        inx
        inx
        iny
        iny
        pla
        dec
        bne @cmp
        lda f:S_TILE
        tax
        lda #16
@cp:    pha
        lda a:.loword(SPRTEXT),y
        sta f:$7F0000,x
        inx
        inx
        iny
        iny
        pla
        dec
        bne @cp
        bra @next_tile
@cmp_fail:
        pla
@nomatch:
        lda f:S_ENT
        clc
        adc #64
        tay
        bra @ent
@next_tile:
        lda f:S_TILE
        cmp f:S_END             ; the last tile may end exactly at $10000
        beq @done
        clc
        adc #32
        sta f:S_TILE
        jmp @tile
@done:  rts
bit_mask:
        .word 1, 2, 4, 8, 16, 32, 64, 128
