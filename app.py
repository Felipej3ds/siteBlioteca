from flask import Flask, render_template, request, redirect, url_for, session, flash, send_from_directory, abort
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from abc import ABC, abstractmethod
from openai import OpenAI

app = Flask(__name__)
app.secret_key = 'chave'

# Configurações do banco de dados
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)


# Modelos do banco de dados
class Biblioteca(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(80), nullable=False)
    autor = db.Column(db.String(80), nullable=False)
    release = db.Column(db.String(20), nullable=False)
    imagem = db.Column(db.String(500), nullable=False)
    generos = db.Column(db.String(20), nullable=False)
    resumos = db.relationship('Resumo', backref='livro', lazy=True)

class Resumo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(80), nullable=False)
    resumo = db.Column(db.String(500), nullable=False)
    biblioteca_id = db.Column(db.Integer, db.ForeignKey('biblioteca.id'), nullable=False)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)

class Avaliacao(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    biblioteca_id = db.Column(db.Integer, db.ForeignKey('biblioteca.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    avaliacao_livro = db.Column(db.Text, nullable=False)
    
    # Relacionamentos
    livro = db.relationship('Biblioteca', backref=db.backref('avaliacoes', lazy=True))
    usuario = db.relationship('User', backref=db.backref('avaliacoes', lazy=True)) 

   
class Command(ABC):
    @abstractmethod
    def execute(self):
        pass

    @abstractmethod
    def undo(self):
        pass
    
    @abstractmethod
    def redo(self):
        pass
    

class CommandAvaliacao(Command):
    def __init__(self, livro_id, user_id, avaliacao_texto=None, avaliacao_id=None):
        self.livro_id = livro_id
        self.user_id = user_id
        self.avaliacao_texto = avaliacao_texto
        self.avaliacao_id = avaliacao_id
        self.deleted = False

    def execute(self):
        if self.avaliacao_id is None:  # Se não há ID de avaliação, então vamos adicionar uma nova
            livro = Biblioteca.query.get(self.livro_id)
            if livro:
                nova_avaliacao = Avaliacao(
                    biblioteca_id=self.livro_id,
                    user_id=self.user_id,
                    avaliacao_livro=self.avaliacao_texto
                )
                db.session.add(nova_avaliacao)
                db.session.commit()
                self.avaliacao_id = nova_avaliacao.id
        else:  # Se há ID de avaliação, então vamos deletá-la
            avaliacao = Avaliacao.query.get(self.avaliacao_id)
            if avaliacao:
                db.session.delete(avaliacao)
                db.session.commit()
                self.deleted = True

    def undo(self):
        if self.deleted:
            livro = Biblioteca.query.get(self.livro_id)
            if livro:
                nova_avaliacao = Avaliacao(
                    biblioteca_id=self.livro_id,
                    user_id=self.user_id,
                    avaliacao_livro=self.avaliacao_texto
                )
                db.session.add(nova_avaliacao)
                db.session.commit()
                self.avaliacao_id = nova_avaliacao.id
                self.deleted = False
        else:
            if self.avaliacao_id:
                avaliacao = Avaliacao.query.get(self.avaliacao_id)
                if avaliacao:
                    db.session.delete(avaliacao)
                    db.session.commit()
                    self.deleted = True

    def redo(self):
        self.execute()


class ChatGPT(ABC):
    chave = ''  
    modelo_inteligencia = 'gpt-3.5-turbo-0125'
    formato_resposta = {"type": "text"}
    conexao = None  # Variável de classe para armazenar a instância única do OpenAI
    _instance = None  # Variável para armazenar a instância única

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super().__new__(cls)
            cls._instance.conexao = OpenAI(api_key=cls.chave)
        return cls._instance
 
    def gerar_texto(self, prompt):
        resposta = self.conexao.chat.completions.create(
            model=self.modelo_inteligencia,
            response_format=self.formato_resposta,
            messages=[{"role": "system", "content": prompt}]
        )
        return resposta.choices[0].message.content
    
    def gerar_recomendacao(self):
        prompt = "gere o nome de um livro aleatório"
        return self.gerar_texto(prompt)



@app.route('/recomendacao')
def rota_recomendacao():
    recomendacao = ChatGPT().gerar_recomendacao()
    return f"Recomendação de Livro: {recomendacao}"

@app.before_request
def require_login():
    allowed_routes = ['login', 'register', 'deletar_conta']
    if request.endpoint not in allowed_routes and 'username' not in session:
        return redirect(url_for('login'))
    
    
# Rota para página do usuário
@app.route('/usuario')
def usuario():
    # Verifica se o usuário está logado
    if 'username' not in session:
        return redirect(url_for('login'))

    return render_template('usuario.html')

from openai import OpenAIError

# Rota para página inicial
@app.route('/home', methods=['GET', 'POST'])
@app.route('/', methods=['GET', 'POST'])
def home():
    if request.method == 'POST':
        titulo = request.form['titulo']
        livro = Biblioteca.query.filter_by(titulo=titulo).first()
        if livro:
            return redirect(url_for('livro', livroname=livro.titulo))
        else:
            livro_nao_encontrado = True

    # Se não houver POST ou se o livro não for encontrado, renderiza a página normalmente
    return render_template('home.html', livros=Biblioteca.query.order_by(Biblioteca.titulo).all())

# Rota para logout
@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('username', None)
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'username' in session:
        return redirect(url_for('home'))

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()

        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            session['username'] = user.username
            return redirect(url_for('home'))
        else:
            error = 'Login não existe ou senha errada.'
            return render_template('login_register.html', error=error, action='/login', is_login=True, title='Login')

    return render_template('login_register.html', action='/login', is_login=True, title='Login')

# Rota para deletar conta
@app.route('/deletar_conta', methods=['GET', 'POST'])
def deletar_conta():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()

        if not user or not check_password_hash(user.password, password):
            flash('Conta não existe ou senha não corresponde a esse username.')
            return render_template('login_register.html', error='Conta não existe ou senha não corresponde a esse username.', action='/deletar_conta', is_login=False, show_delete=True, title='Deletar Conta')

        try:
            db.session.delete(user)
            db.session.commit()
            session.pop('user_id', None)
            session.pop('username', None)
            flash('Sua conta foi deletada com sucesso.')
            return redirect(url_for('register'))
        except Exception as e:
            flash(f'Ocorreu um erro ao deletar sua conta: {str(e)}')
            return render_template('login_register.html', error=f'Ocorreu um erro ao deletar sua conta: {str(e)}', action='/deletar_conta', is_login=False, show_delete=True, title='Deletar Conta')

    return render_template('login_register.html', action='/deletar_conta', is_login=False, show_delete=True, title='Deletar Conta')

# Rota para registro de usuário
@app.route('/register', methods=['GET', 'POST'])
def register():
    if 'username' in session:
        return redirect(url_for('home'))

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        if User.query.filter_by(username=username).first():
            error = 'Este nome de usuário já está cadastrado. Por favor, escolha outro.'
            return render_template('login_register.html', error=error, action='/register', is_register=True, title='Registrar')

        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
        new_user = User(username=username, password=hashed_password)
        db.session.add(new_user)
        db.session.commit()

        flash('Usuário registrado com sucesso! Faça login para continuar.')
        return redirect(url_for('login'))

    return render_template('login_register.html', action='/register', is_register=True, title='Registrar')

@app.route("/livro/<livroname>")
def livro(livroname):
    livro = Biblioteca.query.filter_by(titulo=livroname).first()
    if livro:
        livro.avaliacoes  # Acessar a relação para garantir o carregamento
        return render_template('livro.html', livro=livro)
    else:
        return render_template('livro.html', livro=None)

# Rotas epeciais

@app.route('/adicionar_avaliacao/<int:livro_id>', methods=['POST'])
def adicionar_avaliacao(livro_id):
    if 'username' not in session:
        return redirect(url_for('login'))

    avaliacao_texto = request.form.get('avaliacao')

    # Criar e executar o comando de adicionar avaliação
    command = CommandAvaliacao(livro_id, session['user_id'], avaliacao_texto)
    command.execute()

    # Redirecionar após adicionar a avaliação
    return redirect(url_for('livro', livroname=Biblioteca.query.get(livro_id).titulo))


@app.route('/deletar_avaliacao/<int:avaliacao_id>', methods=['POST'])
def deletar_avaliacao(avaliacao_id):
    if 'username' not in session:
        return redirect(url_for('login'))

    # Criar e executar o comando de deletar avaliação
    command = CommandAvaliacao(None, None, None, avaliacao_id)
    command.execute()

    # Redirecionar após deletar a avaliação
    return redirect(url_for('home'))


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
