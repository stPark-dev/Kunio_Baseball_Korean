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
WIDTHS          = $B19000       ; 1 byte per glyph index
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
ST      = $7E1880
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
FLAG_MAGIC = $A55A
RANGE_EMPTY = $00FF

BUF       = $7E8100
BUF_COLS  = 33                  ; 31 visible + 2 spare for the last glyph
BUF_SIZE  = BUF_COLS*64
SPACE_W   = 6
MAX_LINES = 2
OVERFLOW_X = $4000              ; pen position that suppresses further drawing

; ---- pre-drawn labels (menus, team names): hook on the row writer $91B390 ----
ORIG_ROW_WRITER = $11B395       ; after PHP PHB PHD REP #$30
ROW_OFFSET      = $91AE1E       ; X=col Y=row -> A = window buffer offset
CELL_PUT        = $91B373       ; A=word Y=offset -> current window buffer
ROW_DIRTY_MASK  = $91AE6C
ROW_DIRTY_SET   = $91AD72
LABEL_TABLE     = $B1C000       ; u16 string address per label id (strings follow, bank $B1)
LABEL_MARK      = $C000         ; word 0 of a translated row: %11tt iiii iiii iiii (t=0 top, 1 bottom)
RESERVED        = $B1BF00       ; 512-bit map of kanji-area tiles still used by untranslated labels
KANJI_FONT      = $96D7E5       ; original 16x16 font tiles (0x100-0x2FF), 8 KB
POOL_IMG        = $7E9000       ; WRAM mirror of the tile pool (up to 512 tiles)
POOL_TILES      = 512
LMAP            = $7EB000       ; cache map: 64 entries of (id, columns, unused) = 6 bytes
LMAP_ENTRIES    = 64
LTILES          = $7EB200       ; per map entry: 66 tile numbers (top row cells, then bottom row)
LTILES_STRIDE   = 132
STAGE           = $7ED400       ; render staging: up to 33 columns x 2 tile rows
LST             = $7E18C0       ; label state
L_BASE    = LST+0               ; BG3 name base nibble the pool was set up for
L_POOL0   = LST+2               ; first pool tile number
L_POOLN   = LST+4               ; pool size in tiles
L_NEXT    = LST+6               ; next free tile (relative to pool start)
L_LO      = LST+8               ; dirty tile range in the pool image (inclusive)
L_HI      = LST+10
L_BUSY    = LST+12              ; main thread is updating the range
L_MAPN    = LST+14              ; entries used in the cache map
L_VRAMW   = LST+16              ; VRAM word address of pool tile 0
L_CUR     = LST+18              ; refresh cursor: the allocated pool is re-sent 1 KB per frame so
                                ; that a scene reloading the font block does not leave stale tiles
UPLOAD_CHUNK = 128              ; tiles per NMI for fresh labels (2 KB)
REFRESH_CHUNK = 64              ; tiles per NMI for the background refresh (1 KB)

; scratch direct page used while drawing a glyph
Z       = $1800
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

.segment "CODE"

; ---- fixed entry table (addresses used by build.py) --------------------------
        jml kbb_start           ; $B18000
        jml kbb_main_loop       ; $B18004
        jml kbb_nested_loop     ; $B18008
        jml kbb_nmi             ; $B1800C
        jml kbb_label_row       ; $B18010

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
        ; cache location from the BG3 name base
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
        ; clear the tile buffer
        ldx #0
        lda #0
@clr:   sta f:BUF,x
        inx
        inx
        cpx #BUF_SIZE
        bne @clr
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
        lda z_id
        asl
        tax
        lda f:LABEL_TABLE,x
        tay
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
        lda T_Y
        inc
        inc
        sta T_Y
        lda #0
        bra @set
@overflow:
        lda #OVERFLOW_X         ; no room left: drop the rest of the message
@set:   sta f:PEN_X
        lda f:XCOL0
        sta T_X
        rts

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
        inc z_row
        lda z_row
        cmp #16
        beq @rows_done
        jmp @row
@rows_done:
        lda z_pen
        clc
        adc z_w
        sta z_pen
        sec
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
        tax
        lda a:$0000,x           ; word 0 of the row data (caller's DB)
        and #$C000
        cmp #$C000
        beq @marked
        plx
        pla
        plp
        php                     ; re-execute the replaced instructions
        phb
        phd
        rep #$30
        jml ORIG_ROW_WRITER
@marked:
        lda a:$0000,x             ; marker word
        phy
        phb
        phd
        pea Z
        pld
        ; stack from S+1: D(2) B(1) Y(2) X(2) A(2) P(1) ret(3) n(2) attr(2)
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

; DP = Z. Draws label z_id (top or bottom row per z_tpl bit 12) at z_x/z_y, z_n cells.
label_body:
        jsr pool_setup
        ; cache lookup
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
        jsr redirty_entry
        bra @write
@miss:  jsr label_render
@write:
        ; window cells: tile numbers from the entry's list, bottom row uses the second half
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

; Mark every tile of the entry at z_ent (2 * z_cols tiles) dirty again.
redirty_entry:
        lda #1
        sta f:L_BUSY
        lda z_cols
        asl
        sta z_tmp
        ldx z_ent
@t:     lda f:LTILES,x
        cmp f:L_LO
        bcs @lo
        sta f:L_LO
@lo:    lda f:LTILES,x
        cmp f:L_HI
        bcc @hi
        sta f:L_HI
@hi:    inx
        inx
        dec z_tmp
        bne @t
        lda #0
        sta f:L_BUSY
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

; Render label z_id into staging, allocate 2 * cols pool tiles (skipping reserved
; ones), copy the tiles into the pool image and record them in a new cache entry.
; cols = max(n, ceil(width / 8)), at most n + 4 and never past the screen edge.
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
@cap2:  ; clear the staging area (2 * cols tiles)
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
        ; blit parameters
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
        lda #0
        sta z_pen
        ; draw the string
        phb
        pea $B1B1
        plb
        plb
        lda z_id
        asl
        tax
        lda f:LABEL_TABLE,x
        tay
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
        ; new cache entry (wraps the map when full)
        lda #0
        sta z_row               ; wrap counter
@entry: lda f:L_MAPN
        cmp #LMAP_ENTRIES*6
        bcc @map_ok
        lda #0
        sta f:L_MAPN
        sta f:L_NEXT
@map_ok:
        jsr entry_offset        ; z_ent from the entry byte offset in A
        ; allocate and copy 2 * cols tiles
        lda #1
        sta f:L_BUSY
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
        ; record the tile
        lda z_i
        asl
        clc
        adc z_ent
        tax
        lda z_tile
        sta f:LTILES,x
        ; dirty range
        cmp f:L_LO
        bcs @lo_ok
        sta f:L_LO
@lo_ok: lda z_tile
        cmp f:L_HI
        bcc @hi_ok
        sta f:L_HI
@hi_ok: ; copy 16 bytes: STAGE + i*16 -> POOL_IMG + tile*16
        lda z_i
        asl
        asl
        asl
        asl
        clc
        adc #.loword(STAGE)
        sta z_val
        lda z_tile
        asl
        asl
        asl
        asl
        clc
        adc #.loword(POOL_IMG)
        sta z_dst
        ldy #0
@cp:    tyx
        txa
        clc
        adc z_val
        tax
        lda f:$7E0000,x
        pha
        tya
        clc
        adc z_dst
        tax
        pla
        sta f:$7E0000,x
        iny
        iny
        cpy #16
        bne @cp
        inc z_i
        lda z_cols
        asl
        cmp z_i
        beq @alloc_done
        jmp @tile
@alloc_done:
        lda #0
        sta f:L_BUSY
        ; publish the entry
        lda f:L_MAPN
        tax
        clc
        adc #6
        sta f:L_MAPN
        lda z_id
        sta f:LMAP,x
        lda z_cols
        sta f:LMAP+2,x
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
        cmp #5
        bne @big
        lda #$0184              ; story scenes: only $B840-$BFFF is free
        sta f:L_POOL0
        lda #124
        sta f:L_POOLN
        bra @range
@big:   lda #$0100              ; the 16x16 kanji font area, unused once labels are Korean
        sta f:L_POOL0
        lda #POOL_TILES
        sta f:L_POOLN
        ; seed the pool image with the original kanji tiles so that uploads spanning
        ; reserved tiles rewrite them unchanged
        phb
        ldx #.loword(KANJI_FONT)
        ldy #.loword(POOL_IMG)
        lda #POOL_TILES*16-1
        mvn #^KANJI_FONT, #^POOL_IMG
        plb
@range: lda #0
        sta f:L_NEXT
        sta f:L_MAPN
        sta f:L_CUR
        sta f:L_HI
        lda #$7FFF
        sta f:L_LO
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
        bne @done
        lda #0
        sta f:FLAG
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

; Upload up to UPLOAD_CHUNK dirty pool tiles (DB = 0, M/X 16-bit).
nmi_pool_upload:
        lda f:L_BUSY
        and #$00FF
        beq @check
        rts
@check: lda f:L_POOLN
        bne @ready
        rts                     ; pool never set up (random WRAM after power-on)
@ready: lda f:L_LO
        cmp f:L_HI
        beq @go
        bcc @go
        rts                     ; LO > HI: nothing pending
@go:    lda f:L_HI
        sec
        sbc f:L_LO
        inc
        cmp #UPLOAD_CHUNK
        bcc @len_ok
        lda #UPLOAD_CHUNK
@len_ok:
        tax                     ; X = tiles this frame
        asl
        asl
        asl
        asl
        sta $4365               ; bytes
        lda f:L_LO
        asl
        asl
        asl
        clc
        adc f:L_VRAMW
        sta $2116
        lda f:L_LO
        asl
        asl
        asl
        asl
        clc
        adc #.loword(POOL_IMG)
        sta $4362
        sep #$20
        lda #^POOL_IMG
        sta $4364
        lda #$80
        sta $2115
        lda #$01
        sta $4360
        lda #$18
        sta $4361
        lda #$40
        sta $420B
        rep #$20
        txa
        clc
        adc f:L_LO
        sta f:L_LO
        cmp f:L_HI
        bcc @done
        beq @done
        lda #$7FFF
        sta f:L_LO
        lda #0
        sta f:L_HI
@done:  rts
