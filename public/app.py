from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
from flask import send_file

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///sistema.db'
app.config['SECRET_KEY'] = 'chave-secreta'
db = SQLAlchemy(app)

# ---------- MODELOS ----------
class Cliente(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100))
    telefone = db.Column(db.String(20))
    pontos = db.Column(db.Integer, default=0)  # saldo de pontos

    vendas = db.relationship('Venda', backref='cliente', lazy=True)
    mov_pontos = db.relationship('MovimentacaoPontos', backref='cliente', lazy=True)

class Venda(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey('cliente.id'), nullable=False)
    valor_total = db.Column(db.Float, nullable=False)
    num_parcelas = db.Column(db.Integer, nullable=False)
    data_venda = db.Column(db.DateTime, default=datetime.utcnow)
    forma_pagamento = db.Column(db.String(20), default='dinheiro')
    parcelas = db.relationship('Parcela', backref='venda', lazy=True)

class Parcela(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    venda_id = db.Column(db.Integer, db.ForeignKey('venda.id'), nullable=False)
    numero = db.Column(db.Integer, nullable=False)
    valor = db.Column(db.Float, nullable=False)
    vencimento = db.Column(db.Date, nullable=False)
    pago = db.Column(db.Boolean, default=False)
    data_pagamento = db.Column(db.DateTime, nullable=True)

class MovimentacaoPontos(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey('cliente.id'), nullable=False)
    tipo = db.Column(db.String(10))  # 'credito' ou 'debito'
    pontos = db.Column(db.Integer, nullable=False)
    descricao = db.Column(db.String(200))
    data = db.Column(db.DateTime, default=datetime.utcnow)

# ---------- ROTAS ----------
@app.route('/')
def index():
    total_receber = db.session.query(db.func.sum(Parcela.valor)).filter(Parcela.pago == False).scalar() or 0
    total_atrasado = db.session.query(db.func.sum(Parcela.valor)).filter(Parcela.pago == False, Parcela.vencimento < datetime.now().date()).scalar() or 0
    total_pontos = db.session.query(db.func.sum(Cliente.pontos)).scalar() or 0
    return render_template('index.html', total_receber=total_receber, total_atrasado=total_atrasado, total_pontos=total_pontos)

# --- CRM ---
@app.route('/clientes')
def clientes():
    clientes = Cliente.query.all()
    return render_template('clientes.html', clientes=clientes)

@app.route('/clientes/novo', methods=['GET', 'POST'])
def novo_cliente():
    if request.method == 'POST':
        nome = request.form['nome']
        email = request.form['email']
        telefone = request.form['telefone']
        cliente = Cliente(nome=nome, email=email, telefone=telefone)
        db.session.add(cliente)
        db.session.commit()
        flash('Cliente cadastrado!')
        return redirect(url_for('clientes'))
    return render_template('cliente_form.html')

@app.route('/loja/painel')
def painel_operador():
    hoje = datetime.now().date()
    kpis = {
        'parcelas_hoje': Parcela.query.filter(
            Parcela.pago == False,
            Parcela.vencimento == hoje
        ).count(),
        'parcelas_atrasadas': Parcela.query.filter(
            Parcela.pago == False,
            Parcela.vencimento < hoje
        ).count(),
        'total_receber_hoje': db.session.query(db.func.sum(Parcela.valor)).filter(
            Parcela.pago == False,
            Parcela.vencimento == hoje
        ).scalar() or 0,
        'vendas_hoje': Venda.query.filter(
            db.func.date(Venda.data_venda) == hoje
        ).count()
    }
    ultimas_vendas = Venda.query.order_by(Venda.data_venda.desc()).limit(5).all()
    return render_template('painel_operador.html', kpis=kpis, ultimas_vendas=ultimas_vendas)

# --- Financeiro ---
@app.route('/vendas/nova', methods=['GET', 'POST'])
def nova_venda():
    if request.method == 'POST':
        cliente_id = int(request.form['cliente_id'])
        valor_total = float(request.form['valor_total'])
        num_parcelas = int(request.form['num_parcelas'])
        primeiro_vencimento = datetime.strptime(request.form['primeiro_vencimento'], '%Y-%m-%d').date()
        forma_pagamento = request.form.get('forma_pagamento', 'dinheiro')

        cliente = Cliente.query.get_or_404(cliente_id)
        venda = Venda(
            cliente_id=cliente_id,
            valor_total=valor_total,
            num_parcelas=num_parcelas,
            forma_pagamento=forma_pagamento
        )
        db.session.add(venda)
        db.session.flush()

        valor_parcela = round(valor_total / num_parcelas, 2)
        for i in range(num_parcelas):
            vencimento = primeiro_vencimento + timedelta(days=30 * i)
            db.session.add(Parcela(
                venda_id=venda.id,
                numero=i + 1,
                valor=valor_parcela,
                vencimento=vencimento
            ))
        db.session.commit()
        flash(f'Venda #{venda.id} criada para {cliente.nome}!')
        return redirect(url_for('parcelas'))

    # GET: verifica se veio cliente_id da leitura do QR
    clientes = Cliente.query.order_by(Cliente.nome).all()
    cliente_pre = None
    cliente_id_qs = request.args.get('cliente_id', type=int)
    if cliente_id_qs:
        cliente_pre = Cliente.query.get(cliente_id_qs)
    return render_template('nova_venda.html', clientes=clientes, cliente_pre=cliente_pre)

@app.context_processor
def inject_atalho_qr():
    # Exibe o atalho em todas as telas da loja, exceto na própria tela do leitor
    caminhos_sem_atalho = {'ler_qrcode'}
    mostrar = request.endpoint not in caminhos_sem_atalho
    return dict(mostrar_atalho_qr=mostrar)

@app.route('/parcelas')
def parcelas():
    parcelas = Parcela.query.order_by(Parcela.vencimento).all()
    return render_template('parcelas.html', parcelas=parcelas)

@app.route('/parcelas/<int:parcela_id>/pagar', methods=['POST'])
def pagar_parcela(parcela_id):
    parcela = Parcela.query.get_or_404(parcela_id)
    if not parcela.pago:
        parcela.pago = True
        parcela.data_pagamento = datetime.utcnow()
        
        # --- Fidelidade: creditar pontos (1 ponto por R$1) ---
        cliente = parcela.venda.cliente
        pontos_ganhos = int(parcela.valor)  # arredonda para baixo
        cliente.pontos += pontos_ganhos
        
        mov = MovimentacaoPontos(
            cliente_id=cliente.id,
            tipo='credito',
            pontos=pontos_ganhos,
            descricao=f'Pagamento parcela {parcela.numero}/{parcela.venda.num_parcelas} da venda #{parcela.venda.id}'
        )
        db.session.add(mov)
        db.session.commit()
        flash(f'Parcela paga! {pontos_ganhos} pontos creditados.')
    return redirect(url_for('parcelas'))

# --- Fidelidade ---
@app.route('/clientes/<int:cliente_id>/pontos')
def extrato_pontos(cliente_id):
    cliente = Cliente.query.get_or_404(cliente_id)
    movimentacoes = MovimentacaoPontos.query.filter_by(cliente_id=cliente_id).order_by(MovimentacaoPontos.data.desc()).all()
    return render_template('pontos.html', cliente=cliente, movimentacoes=movimentacoes)

import qrcode
import io

# ---------- ÁREA DO CLIENTE (Mobile) ----------
@app.route('/cliente_acesso')
def cliente_acesso():
    return render_template('cliente_acesso.html')

@app.route('/cliente_acesso', methods=['POST'])
def cliente_acesso_post():
    cliente_id = request.form.get('cliente_id')
    if not cliente_id:
        flash('Informe o ID do cliente.')
        return redirect(url_for('cliente_acesso'))
    return redirect(url_for('painel_cliente', cliente_id=cliente_id))

@app.route('/cliente/<int:cliente_id>')
def painel_cliente(cliente_id):
    cliente = Cliente.query.get_or_404(cliente_id)
    parcelas_abertas = Parcela.query.join(Venda).filter(
        Venda.cliente_id == cliente_id,
        Parcela.pago == False
    ).order_by(Parcela.vencimento).all()
    return render_template('painel_cliente.html', cliente=cliente, parcelas_abertas=parcelas_abertas)

@app.route('/loja/ler_qrcode')
def ler_qrcode():
    return render_template('leitor_qrcode.html')

from flask import jsonify, request

@app.route('/api/qrcode/validar', methods=['POST'])
def validar_qrcode():
    # Garante que veio JSON mesmo
    data = request.get_json(silent=True)
    if not data or 'payload' not in data:
        return jsonify({'ok': False, 'erro': 'Payload ausente ou inválido'}), 400

    payload = data['payload'].strip()
    partes = payload.split(':')

    if len(partes) != 3 or partes[0] != 'cliente':
        return jsonify({'ok': False, 'erro': 'Formato de QR inválido'}), 400

    try:
        cliente_id = int(partes[1])
    except ValueError:
        return jsonify({'ok': False, 'erro': 'ID do cliente inválido'}), 400

    cliente = Cliente.query.get(cliente_id)
    if not cliente:
        return jsonify({'ok': False, 'erro': 'Cliente não encontrado'}), 404

    return jsonify({
        'ok': True,
        'cliente': {
            'id': cliente.id,
            'nome': cliente.nome,
            'pontos': cliente.pontos
        }
    })

@app.route('/cliente/<int:cliente_id>/qrcode')
def cliente_qrcode(cliente_id):
    cliente = Cliente.query.get_or_404(cliente_id)
    # Conteúdo do QR Code: identificação única
    qr_data = f"cliente:{cliente.id}:{cliente.nome}"
    
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(qr_data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return send_file(buf, mimetype='image/png')

# ---------- INICIALIZAÇÃO ----------
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)