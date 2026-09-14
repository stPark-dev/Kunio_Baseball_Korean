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

.segment "CODE"

; ---- fixed entry table (addresses used by build.py) --------------------------
        jml kbb_start           ; $B18000
        jml kbb_main_loop       ; $B18004
        jml kbb_nested_loop     ; $B18008
        jml kbb_nmi             ; $B1800C

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
        sta f:z_tmp+Z+$7E0000
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
        adc f:z_tmp+Z+$7E0000
        sta f:z_tmp+Z+$7E0000
        bra @next
@done:  lda f:z_tmp+Z+$7E0000
        rts

sfx:
        lda f:SFX_FLAG
        beq @no
        lda #$0035
        jsl SFX_PLAY
@no:    rts

; A = glyph index. Draws it at PEN_X on LINE and advances PEN_X.
draw_glyph:
        phd
        pea Z
        pld
        sta z_idx
        tax
        lda f:WIDTHS,x
        and #$00FF
        sta z_w
        ; never draw past the buffer
        clc
        adc f:PEN_X
        cmp #(BUF_COLS-2)*8+1
        bcc @fits
        jmp @skip
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
        lda f:PEN_X
        and #$0007
        sta z_shift
        lda f:PEN_X
        lsr
        lsr
        lsr
        sta z_col
        asl
        asl
        asl
        asl
        asl
        asl                     ; col * 64
        sta z_dst
        lda f:LINE
        asl
        asl
        asl
        asl
        asl                     ; line * 32 (two tile rows)
        clc
        adc z_dst
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
        asl                     ; +16 for the lower tile row
        clc
        adc z_tmp
        clc
        adc z_dst
        tax
        sep #$20
        lda z_val+1
        ora f:BUF,x
        sta f:BUF,x
        lda z_val+1
        ora f:BUF+1,x
        sta f:BUF+1,x
        lda z_val
        ora f:BUF+64,x
        sta f:BUF+64,x
        lda z_val
        ora f:BUF+65,x
        sta f:BUF+65,x
        lda z_spill+1
        ora f:BUF+128,x
        sta f:BUF+128,x
        lda z_spill+1
        ora f:BUF+129,x
        sta f:BUF+129,x
        rep #$20
        inc z_row
        lda z_row
        cmp #16
        bne @row
        lda f:PEN_X
        clc
        adc z_w
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
@skip:  pld
        rts

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
        plb
        ply
        plx
        pla
        plp
        jml ORIG_NMI
